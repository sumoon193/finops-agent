"""GovernanceTicket 服务：异常 finding 只经审批创建，幂等防重。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

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


class TicketService:
    """按 finding_id 幂等创建人工工单，并记录审计。"""

    def __init__(self) -> None:
        self._tickets: dict[str, GovernanceTicket] = {}
        self.audit: list[dict[str, Any]] = []

    def create(self, finding: AnomalyFinding) -> GovernanceTicket:
        if finding.finding_id in self._tickets:
            return self._tickets[finding.finding_id]
        ticket = GovernanceTicket(
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
