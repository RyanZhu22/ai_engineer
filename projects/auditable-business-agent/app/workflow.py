from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from typing_extensions import TypedDict

from app.models import ActionType, Approval, ApprovalStatus, Decision, RequestType, SupportRequest
from app.service import CaseService


class CaseWorkflowState(TypedDict, total=False):
    case_id: str
    customer_id: str
    order_id: str
    request_type: str
    summary: str
    submitted_on: str
    assessment_on: str
    request_id: str
    action: str
    reason: str
    rule_id: str
    requires_approval: bool
    status: str
    ticket_id: str | None


def build_workflow(service: CaseService, checkpointer: Any):
    def assess_case(state: CaseWorkflowState) -> dict[str, Any]:
        request = SupportRequest(
            case_id=state["case_id"],
            customer_id=state["customer_id"],
            order_id=state["order_id"],
            request_type=RequestType(state["request_type"]),
            summary=state["summary"],
            submitted_on=date.fromisoformat(state["submitted_on"]),
        )
        decision = service.assess(
            request,
            request_id=state["request_id"],
            today=date.fromisoformat(state["assessment_on"]),
        )
        return _decision_state(decision)

    def needs_approval(state: CaseWorkflowState) -> Literal["record_approval_request", "complete"]:
        if state["requires_approval"]:
            return "record_approval_request"
        return "complete"

    def record_approval_request(state: CaseWorkflowState) -> dict[str, str]:
        service.record_approval_request(
            case_id=state["case_id"],
            decision=_decision_from_state(state),
            request_id=state["request_id"],
        )
        return {"status": "pending_approval"}

    def wait_for_approval(state: CaseWorkflowState) -> dict[str, Any]:
        decision_data = interrupt(
            {
                "case_id": state["case_id"],
                "action": state["action"],
                "reason": state["reason"],
                "rule_id": state["rule_id"],
            }
        )
        approval = Approval(
            case_id=state["case_id"],
            approver_id=str(decision_data["approver_id"]),
            status=ApprovalStatus(str(decision_data["status"])),
            decided_at=datetime.fromisoformat(str(decision_data["decided_at"])),
            note=str(decision_data.get("note", "")),
        )
        execution = service.apply_approval(
            case_id=state["case_id"],
            decision=_decision_from_state(state),
            approval=approval,
            request_id=state["request_id"],
        )
        if execution is None:
            return {"status": "rejected", "ticket_id": None}
        return {
            "status": "completed",
            "ticket_id": execution.ticket.ticket_id,
        }

    def complete(state: CaseWorkflowState) -> dict[str, str]:
        return {"status": state.get("status", "completed")}

    builder = StateGraph(CaseWorkflowState)
    builder.add_node("assess_case", assess_case)
    builder.add_node("record_approval_request", record_approval_request)
    builder.add_node("wait_for_approval", wait_for_approval)
    builder.add_node("complete", complete)
    builder.add_edge(START, "assess_case")
    builder.add_conditional_edges("assess_case", needs_approval)
    builder.add_edge("record_approval_request", "wait_for_approval")
    builder.add_edge("wait_for_approval", "complete")
    builder.add_edge("complete", END)
    return builder.compile(checkpointer=checkpointer)


def _decision_state(decision: Decision) -> dict[str, Any]:
    return {
        "action": decision.action.value,
        "reason": decision.reason,
        "rule_id": decision.rule_id,
        "requires_approval": decision.requires_approval,
    }


def _decision_from_state(state: CaseWorkflowState) -> Decision:
    return Decision(
        action=ActionType(state["action"]),
        reason=state["reason"],
        rule_id=state["rule_id"],
        requires_approval=state["requires_approval"],
    )
