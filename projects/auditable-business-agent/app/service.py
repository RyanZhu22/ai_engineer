from __future__ import annotations

from datetime import date

from app.cases import InMemoryCaseStore
from app.knowledge import KnowledgeBase, default_knowledge_base
from app.models import (
    ActionType,
    Approval,
    ApprovalStatus,
    Decision,
    SupportRequest,
    TicketExecution,
)
from app.policy import PolicyEngine
from app.ports import AuditSink, CaseStore, OrderReader, TicketWriter
from app.reply import ReplyGenerator, configured_reply_generator


class CaseService:
    def __init__(
        self,
        *,
        case_store: CaseStore | None = None,
        order_service: OrderReader,
        ticket_service: TicketWriter,
        audit_log: AuditSink,
        policy_engine: PolicyEngine | None = None,
        knowledge_base: KnowledgeBase | None = None,
        reply_generator: ReplyGenerator | None = None,
    ) -> None:
        self._case_store = case_store or InMemoryCaseStore()
        self._order_service = order_service
        self._ticket_service = ticket_service
        self._audit_log = audit_log
        self._policy_engine = policy_engine or PolicyEngine()
        self._knowledge_base = knowledge_base or default_knowledge_base()
        self._reply_generator = reply_generator or configured_reply_generator()

    def assess(
        self,
        request: SupportRequest,
        *,
        request_id: str,
        today: date,
    ) -> Decision:
        self._case_store.save(request)
        self._audit_log.append(
            case_id=request.case_id,
            event_type="request_received",
            actor_type="customer",
            actor_id=request.customer_id,
            payload={
                "order_id": request.order_id,
                "request_type": request.request_type.value,
                "summary": request.summary,
            },
            request_id=request_id,
        )
        evidence = self._knowledge_base.search(request_type=request.request_type, query=request.summary)
        self._audit_log.append(
            case_id=request.case_id,
            event_type="knowledge_retrieved",
            actor_type="system",
            actor_id="policy_retriever",
            payload={
                "query": request.summary,
                "evidence": [
                    {
                        "document_id": item.document_id,
                        "title": item.title,
                        "version": item.version,
                        "excerpt": item.excerpt,
                        "score": item.score,
                        "chunk_index": item.chunk_index,
                        "source": item.source,
                    }
                    for item in evidence
                ],
            },
            request_id=request_id,
        )
        order = self._order_service.get_order(request.order_id)
        self._audit_log.append(
            case_id=request.case_id,
            event_type="order_queried",
            actor_type="system",
            actor_id="order_service",
            payload={"order_id": request.order_id, "found": order is not None},
            request_id=request_id,
        )

        decision = self._policy_engine.evaluate(request, order, today=today)
        self._audit_log.append(
            case_id=request.case_id,
            event_type="rule_evaluated",
            actor_type="system",
            actor_id="policy_engine",
            payload={
                "rule_id": decision.rule_id,
                "action": decision.action.value,
                "reason": decision.reason,
            },
            request_id=request_id,
        )
        reply, provider = self._reply_generator.generate(
            summary=request.summary,
            decision=decision,
            evidence=evidence,
        )
        self._audit_log.append(
            case_id=request.case_id,
            event_type="reply_generated",
            actor_type="system",
            actor_id="reply_generator",
            payload={"provider": provider, "reply": reply},
            request_id=request_id,
        )
        self._audit_log.append(
            case_id=request.case_id,
            event_type="action_proposed",
            actor_type="system",
            actor_id="case_service",
            payload={
                "action": decision.action.value,
                "requires_approval": decision.requires_approval,
            },
            request_id=request_id,
        )
        return decision

    def record_approval_request(
        self,
        *,
        case_id: str,
        decision: Decision,
        request_id: str,
    ) -> None:
        if not decision.requires_approval:
            raise ValueError("This action does not require approval")
        self._audit_log.append(
            case_id=case_id,
            event_type="approval_requested",
            actor_type="system",
            actor_id="case_service",
            payload={"action": decision.action.value, "rule_id": decision.rule_id},
            request_id=request_id,
        )

    def apply_approval(
        self,
        *,
        case_id: str,
        decision: Decision,
        approval: Approval,
        request_id: str,
    ) -> TicketExecution | None:
        if approval.case_id != case_id:
            raise ValueError("Approval case does not match the proposed action")
        if not decision.requires_approval:
            raise ValueError("This action does not require approval and cannot be executed here")

        event_type = f"approval_{approval.status.value}"
        self._audit_log.append(
            case_id=case_id,
            event_type=event_type,
            actor_type="approver",
            actor_id=approval.approver_id,
            payload={
                "note": approval.note,
                "action": decision.action.value,
                "decided_at": approval.decided_at.isoformat(),
            },
            request_id=request_id,
        )
        if approval.status is ApprovalStatus.REJECTED:
            return None

        ticket_type = self._ticket_type_for(decision.action)
        execution = self._ticket_service.create_ticket(
            case_id=case_id,
            ticket_type=ticket_type,
            idempotency_key=f"{case_id}:{decision.action.value}",
        )
        self._audit_log.append(
            case_id=case_id,
            event_type="action_executed" if execution.created else "action_execution_reused",
            actor_type="system",
            actor_id="ticket_service",
            payload={
                "ticket_id": execution.ticket.ticket_id,
                "ticket_type": execution.ticket.ticket_type,
                "idempotency_key": execution.ticket.idempotency_key,
            },
            request_id=request_id,
        )
        return execution

    @staticmethod
    def _ticket_type_for(action: ActionType) -> str:
        mapping = {
            ActionType.CREATE_RETURN_TICKET: "return",
            ActionType.CREATE_REPAIR_TICKET: "repair",
            ActionType.ESCALATE_TO_SPECIALIST: "specialist_review",
        }
        try:
            return mapping[action]
        except KeyError as error:
            raise ValueError(f"Action {action} has no side-effecting ticket type") from error
