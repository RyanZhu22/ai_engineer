from __future__ import annotations

from datetime import date

from app.db import build_session_factory
from app.db_models import OrderRecord
from app.models import OrderStatus


SAMPLE_ORDERS = (
    OrderRecord(
        order_id="ORD-100",
        customer_id="customer-1",
        status=OrderStatus.DELIVERED.value,
        shipped_on=date(2026, 9, 7),
        delivered_on=date(2026, 9, 10),
    ),
    OrderRecord(
        order_id="ORD-101",
        customer_id="customer-1",
        status=OrderStatus.SHIPPED.value,
        shipped_on=date(2026, 9, 14),
        delivered_on=None,
    ),
    OrderRecord(
        order_id="ORD-200",
        customer_id="customer-2",
        status=OrderStatus.DELIVERED.value,
        shipped_on=date(2025, 7, 1),
        delivered_on=date(2025, 7, 5),
    ),
)


def seed_orders() -> int:
    session_factory = build_session_factory()
    inserted = 0
    with session_factory.begin() as session:
        for sample in SAMPLE_ORDERS:
            if session.get(OrderRecord, sample.order_id) is None:
                session.add(sample)
                inserted += 1
    return inserted


if __name__ == "__main__":
    print(f"Inserted {seed_orders()} sample orders.")
