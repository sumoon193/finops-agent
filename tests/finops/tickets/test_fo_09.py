"""FO-09 异常归因与 GovernanceTicket：异常 finding 只经审批创建幂等人工工单。"""

from app.finops.anomaly.attribution import AnomalyFinding
from app.finops.tickets.service import (
    AuthorizedQueryPlan,
    FO09Input,
    FO09Result,
    TicketService,
)

FINDING = AnomalyFinding(
    finding_id="f1",
    query_id="q1",
    kind="cost-spike",
    severity="high",
    detail="monthly spend +300%",
)


def test_ticket_creation_requires_approval():
    result = AuthorizedQueryPlan().execute(FO09Input(finding=FINDING, approved=False))
    assert isinstance(result, FO09Result)
    assert result.status == "blocked"
    assert "approval-required" in result.state_events
    assert result.ticket is None


def test_approved_finding_creates_ticket():
    result = AuthorizedQueryPlan().execute(FO09Input(finding=FINDING, approved=True))
    assert result.status == "completed"
    assert result.ticket is not None
    assert result.ticket.finding_id == "f1"


def test_ticket_creation_is_idempotent():
    service = TicketService()
    plan = AuthorizedQueryPlan(service=service)
    first = plan.execute(FO09Input(finding=FINDING, approved=True))
    second = plan.execute(FO09Input(finding=FINDING, approved=True))
    assert first.ticket.ticket_id == second.ticket.ticket_id
    assert len(service.audit) == 1  # created exactly once


def test_ticket_carries_finding_reference_and_audit():
    result = AuthorizedQueryPlan().execute(FO09Input(finding=FINDING, approved=True))
    assert result.ticket.finding_id == FINDING.finding_id
    assert result.audit["finding_id"] == FINDING.finding_id
