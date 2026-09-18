from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from app.audit import AppendOnlyAuditLog
from app.cases import InMemoryCaseStore
from app.knowledge import Evidence, KnowledgeBase, default_knowledge_base
from app.models import Decision, Order, OrderStatus, RequestType, SupportRequest
from app.policy import PolicyEngine
from app.reply import ReplyGenerator, TemplateReplyGenerator
from app.service import CaseService
from app.tools import MockOrderService, MockTicketService


class EmptyKnowledgeBase:
    def search(self, *, request_type: RequestType, query: str, limit: int = 3) -> tuple[Evidence, ...]:
        return ()


class FailingReplyGenerator(ReplyGenerator):
    def generate(
        self,
        *,
        summary: str,
        decision: Decision,
        evidence: Sequence[Evidence],
    ) -> tuple[str, str]:
        raise RuntimeError("model unavailable")


def _order(item: dict[str, object]) -> Order:
    delivered_on = item.get("delivered_on")
    return Order(
        order_id=str(item.get("order_id", "ORD-EVAL")),
        customer_id=str(item.get("order_customer_id", item.get("customer_id", "customer-eval"))),
        status=OrderStatus(str(item["order_status"])),
        shipped_on=date.fromisoformat(str(item.get("shipped_on", "2026-01-01"))),
        delivered_on=date.fromisoformat(str(delivered_on)) if delivered_on else None,
    )


def _request(item: dict[str, object], order: Order) -> SupportRequest:
    return SupportRequest(
        case_id=str(item.get("case_id", f"CASE-{item['name']}")),
        customer_id=str(item.get("customer_id", "customer-eval")),
        order_id=order.order_id,
        request_type=RequestType(str(item["request_type"])),
        summary=str(item.get("summary", item["name"])),
        submitted_on=date.fromisoformat(str(item.get("today", "2026-09-15"))),
    )


def _service_case(
    item: dict[str, object],
    *,
    knowledge_base: KnowledgeBase,
    reply_generator: ReplyGenerator | None = None,
) -> tuple[Decision, AppendOnlyAuditLog]:
    order = _order(item)
    request = _request(item, order)
    audit_log = AppendOnlyAuditLog()
    service = CaseService(
        order_service=MockOrderService([order]),
        ticket_service=MockTicketService(),
        audit_log=audit_log,
        knowledge_base=knowledge_base,
        reply_generator=reply_generator or TemplateReplyGenerator(),
    )
    return service.assess(request, request_id=f"golden-{request.case_id}", today=request.submitted_on), audit_log


def _run_policy_case(item: dict[str, object]) -> None:
    order = _order(item)
    request = _request(item, order)
    actual = PolicyEngine().evaluate(request, order, today=request.submitted_on).rule_id
    assert actual == item["expected_rule_id"], f"{item['name']}: {actual}"


def _run_document_missing_case(item: dict[str, object]) -> None:
    decision, audit_log = _service_case(item, knowledge_base=EmptyKnowledgeBase())
    assert decision.rule_id == item["expected_rule_id"], f"{item['name']}: {decision.rule_id}"
    case_id = str(item.get("case_id", f"CASE-{item['name']}"))
    retrieved = next(event for event in audit_log.events_for_case(case_id) if event.event_type == "knowledge_retrieved")
    assert retrieved.payload["evidence"] == [], f"{item['name']}: policy evidence was not empty"


def _run_model_failure_case(item: dict[str, object]) -> None:
    decision, audit_log = _service_case(
        item,
        knowledge_base=default_knowledge_base(),
        reply_generator=FailingReplyGenerator(),
    )
    assert decision.rule_id == item["expected_rule_id"], f"{item['name']}: {decision.rule_id}"
    case_id = str(item.get("case_id", f"CASE-{item['name']}"))
    events = audit_log.events_for_case(case_id)
    failed = next(event for event in events if event.event_type == "reply_generation_failed")
    generated = next(event for event in events if event.event_type == "reply_generated")
    assert failed.payload["fallback_provider"] == "template", f"{item['name']}: fallback was not recorded"
    assert generated.payload["provider"] == "template", f"{item['name']}: template fallback was not used"


def _run_permission_case(item: dict[str, object]) -> None:
    decision, _ = _service_case(item, knowledge_base=default_knowledge_base())
    assert decision.rule_id == item["expected_rule_id"], f"{item['name']}: {decision.rule_id}"


def _run_duplicate_case(item: dict[str, object]) -> None:
    store = InMemoryCaseStore()
    first = SupportRequest(
        case_id=str(item["case_id"]),
        customer_id="customer-eval",
        order_id="ORD-EVAL",
        request_type=RequestType.TRACKING,
        summary="查询物流。",
        submitted_on=date(2026, 9, 15),
    )
    conflicting = SupportRequest(
        case_id=first.case_id,
        customer_id=first.customer_id,
        order_id=first.order_id,
        request_type=first.request_type,
        summary="修改为退货请求。",
        submitted_on=first.submitted_on,
    )
    store.save(first)
    try:
        store.save(conflicting)
    except ValueError as error:
        assert str(error) == str(item["expected_error"]), f"{item['name']}: {error}"
    else:
        raise AssertionError(f"{item['name']}: conflicting duplicate was accepted")


def main() -> None:
    cases = json.loads((Path(__file__).parent / "golden_cases.json").read_text(encoding="utf-8"))
    runners = {
        "policy": _run_policy_case,
        "document_missing": _run_document_missing_case,
        "model_failure": _run_model_failure_case,
        "permission": _run_permission_case,
        "duplicate": _run_duplicate_case,
    }
    for item in cases:
        kind = str(item.get("kind", "policy"))
        try:
            runner = runners[kind]
        except KeyError as error:
            raise AssertionError(f"Unknown golden case kind: {kind}") from error
        runner(item)
    print(f"PASS: {len(cases)} golden cases")


if __name__ == "__main__":
    main()
