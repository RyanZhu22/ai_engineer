from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from app.models import Order, OrderStatus, RequestType, SupportRequest
from app.policy import PolicyEngine


def main() -> None:
    cases = json.loads((Path(__file__).parent / "golden_cases.json").read_text(encoding="utf-8"))
    engine = PolicyEngine()
    for item in cases:
        order = Order("ORD-EVAL", "customer-eval", OrderStatus(item["order_status"]), date(2026, 1, 1), date.fromisoformat(item["delivered_on"]) if item["delivered_on"] else None)
        request = SupportRequest("CASE-EVAL", "customer-eval", order.order_id, RequestType(item["request_type"]), item["name"], date.fromisoformat(item["today"]))
        actual = engine.evaluate(request, order, today=date.fromisoformat(item["today"])).rule_id
        assert actual == item["expected_rule_id"], f"{item['name']}: {actual}"
    print(f"PASS: {len(cases)} golden cases")


if __name__ == "__main__":
    main()
