from __future__ import annotations

from app.models import Order, Ticket, TicketExecution, new_id


class MockOrderService:
    def __init__(self, orders: list[Order]) -> None:
        self._orders = {order.order_id: order for order in orders}

    def get_order(self, order_id: str) -> Order | None:
        return self._orders.get(order_id)


class MockTicketService:
    """Simulates a side-effecting system and enforces idempotent ticket creation."""

    def __init__(self) -> None:
        self._tickets_by_idempotency_key: dict[str, Ticket] = {}

    def create_ticket(
        self,
        *,
        case_id: str,
        ticket_type: str,
        idempotency_key: str,
    ) -> TicketExecution:
        existing = self._tickets_by_idempotency_key.get(idempotency_key)
        if existing is not None:
            return TicketExecution(ticket=existing, created=False)

        ticket = Ticket(
            ticket_id=f"TKT-{new_id()}",
            case_id=case_id,
            ticket_type=ticket_type,
            idempotency_key=idempotency_key,
        )
        self._tickets_by_idempotency_key[idempotency_key] = ticket
        return TicketExecution(ticket=ticket, created=True)

    @property
    def ticket_count(self) -> int:
        return len(self._tickets_by_idempotency_key)
