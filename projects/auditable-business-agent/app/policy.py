from __future__ import annotations

from datetime import date

from app.models import ActionType, Decision, Order, OrderStatus, RequestType, SupportRequest


RETURN_WINDOW_DAYS = 7
WARRANTY_DAYS = 365


class PolicyEngine:
    """Deterministic policies. LLM output must not override these decisions."""

    def evaluate(
        self,
        request: SupportRequest,
        order: Order | None,
        *,
        today: date,
    ) -> Decision:
        if order is None:
            return Decision(
                action=ActionType.ESCALATE_TO_SPECIALIST,
                reason="未找到订单，需人工核验订单信息。",
                rule_id="ORDER_NOT_FOUND",
                requires_approval=True,
            )

        if order.customer_id != request.customer_id:
            return Decision(
                action=ActionType.ESCALATE_TO_SPECIALIST,
                reason="订单不属于当前客户，需人工核验权限。",
                rule_id="ORDER_OWNERSHIP_MISMATCH",
                requires_approval=True,
            )

        if request.request_type is RequestType.TRACKING:
            return self._tracking_decision(order)

        if request.request_type is RequestType.RETURN:
            return self._return_decision(order, today=today)

        if request.request_type is RequestType.DEFECT:
            return self._defect_decision(order, today=today)

        raise ValueError(f"Unsupported request type: {request.request_type}")

    def _tracking_decision(self, order: Order) -> Decision:
        if order.status is OrderStatus.SHIPPED:
            return Decision(
                action=ActionType.ANSWER_ONLY,
                reason="订单已发货，提供物流状态。",
                rule_id="TRACKING_SHIPPED",
                requires_approval=False,
            )
        if order.status is OrderStatus.DELIVERED:
            return Decision(
                action=ActionType.ANSWER_ONLY,
                reason="订单已送达，提供签收状态。",
                rule_id="TRACKING_DELIVERED",
                requires_approval=False,
            )
        return Decision(
            action=ActionType.ANSWER_ONLY,
            reason="订单已取消，无法提供物流跟踪。",
            rule_id="TRACKING_CANCELLED",
            requires_approval=False,
        )

    def _return_decision(self, order: Order, *, today: date) -> Decision:
        days = self._days_since_delivery(order, today=today)
        if days is not None and 0 <= days <= RETURN_WINDOW_DAYS:
            return Decision(
                action=ActionType.CREATE_RETURN_TICKET,
                reason=f"签收后 {days} 天，仍在 {RETURN_WINDOW_DAYS} 天退货期内。",
                rule_id="RETURN_WITHIN_WINDOW",
                requires_approval=True,
            )
        return Decision(
            action=ActionType.ANSWER_ONLY,
            reason=f"订单不在 {RETURN_WINDOW_DAYS} 天退货期内，不能自动创建退货工单。",
            rule_id="RETURN_OUTSIDE_WINDOW",
            requires_approval=False,
        )

    def _defect_decision(self, order: Order, *, today: date) -> Decision:
        days = self._days_since_delivery(order, today=today)
        if days is not None and 0 <= days <= WARRANTY_DAYS:
            return Decision(
                action=ActionType.CREATE_REPAIR_TICKET,
                reason=f"签收后 {days} 天，仍在 {WARRANTY_DAYS} 天保修期内。",
                rule_id="DEFECT_WITHIN_WARRANTY",
                requires_approval=True,
            )
        return Decision(
            action=ActionType.ESCALATE_TO_SPECIALIST,
            reason="订单不在自动保修范围内，需人工判断例外情况。",
            rule_id="DEFECT_OUTSIDE_WARRANTY",
            requires_approval=True,
        )

    @staticmethod
    def _days_since_delivery(order: Order, *, today: date) -> int | None:
        if order.status is not OrderStatus.DELIVERED or order.delivered_on is None:
            return None
        if order.delivered_on > today:
            raise ValueError("Order delivery date cannot be in the future")
        return (today - order.delivered_on).days
