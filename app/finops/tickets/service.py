"""GovernanceTicket 服务：异常 finding 只经审批创建，幂等防重。"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.finops.anomaly.attribution import AnomalyFinding


@dataclass
class GovernanceTicket:
    ticket_id: str
    finding_id: str
    status: str = "open"


@dataclass
class FO09Input:
    finding: AnomalyFinding
    approved: bool


@dataclass
class FO09Result:
    status: str
    ticket: GovernanceTicket | None = None
    state_events: list[str] = field(default_factory=list)
    audit: dict[str, Any] = field(default_factory=dict)


class GitHubIssuesTicketAdapter:
    """Real GitHub Issues adapter; missing authorization is an explicit block."""

    def __init__(self, token: str, repository: str) -> None:
        self.token = token.strip()
        self.repository = repository.strip().strip("/")
        if not self.token or not self.repository or "/" not in self.repository:
            raise RuntimeError("GitHub Issues adapter blocked: GITHUB_TOKEN and GITHUB_REPOSITORY are required")

    def create(self, finding: AnomalyFinding) -> GovernanceTicket:
        payload = json.dumps({
            "title": f"FinOps anomaly: {finding.kind} ({finding.finding_id})",
            "body": f"Finding: {finding.finding_id}\nSeverity: {finding.severity}\n\n{finding.detail}",
        }).encode("utf-8")
        request = Request(
            f"https://api.github.com/repos/{self.repository}/issues",
            data=payload,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
                "User-Agent": "finops-agent",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=20) as response:
                result = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError) as exc:
            raise RuntimeError(f"GitHub Issues request failed: {exc.__class__.__name__}") from exc
        number = result.get("number")
        if not number:
            raise RuntimeError("GitHub Issues response missing issue number")
        return GovernanceTicket(ticket_id=f"github-{number}", finding_id=finding.finding_id)


class TicketService:
    """按 finding_id 幂等创建人工工单，并记录审计。"""

    def __init__(self, adapter: GitHubIssuesTicketAdapter | None = None) -> None:
        self._tickets: dict[str, GovernanceTicket] = {}
        self.audit: list[dict[str, Any]] = []
        configured = os.getenv("FINOPS_TICKET_ADAPTER", "offline").lower()
        if configured == "github":
            adapter = adapter or GitHubIssuesTicketAdapter(
                os.getenv("GITHUB_TOKEN", ""), os.getenv("GITHUB_REPOSITORY", "")
            )
        self.adapter = adapter

    def create(self, finding: AnomalyFinding) -> GovernanceTicket:
        if finding.finding_id in self._tickets:
            return self._tickets[finding.finding_id]
        ticket = self.adapter.create(finding) if self.adapter else GovernanceTicket(
            ticket_id=f"tkt-{finding.finding_id}", finding_id=finding.finding_id
        )
        self._tickets[finding.finding_id] = ticket
        self.audit.append(
            {
                "finding_id": finding.finding_id,
                "ticket_id": ticket.ticket_id,
                "action": "created",
            }
        )
        return ticket


class AuthorizedQueryPlan:
    def __init__(self, service: TicketService | None = None) -> None:
        self.service = service or TicketService()

    def execute(self, input: FO09Input) -> FO09Result:
        if not input.approved:
            return FO09Result(
                status="blocked",
                state_events=["planned", "approval-required"],
                audit={"finding_id": input.finding.finding_id, "reason": "approval required"},
            )
        ticket = self.service.create(input.finding)
        return FO09Result(
            status="completed",
            ticket=ticket,
            state_events=["planned", "approved", "completed"],
            audit={
                "finding_id": input.finding.finding_id,
                "ticket_id": ticket.ticket_id,
            },
        )
