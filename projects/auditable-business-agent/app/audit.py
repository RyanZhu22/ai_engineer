from __future__ import annotations

from copy import deepcopy
from types import MappingProxyType
from typing import Any, Mapping

from app.models import AuditEvent, new_id, utc_now


def freeze_payload(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType(deepcopy(dict(payload)))


class AppendOnlyAuditLog:
    """In-memory audit log for P0. Later replaced by an append-only database table."""

    def __init__(self) -> None:
        self._events: list[AuditEvent] = []

    def append(
        self,
        *,
        case_id: str,
        event_type: str,
        actor_type: str,
        actor_id: str,
        payload: Mapping[str, Any],
        request_id: str,
    ) -> AuditEvent:
        event = AuditEvent(
            event_id=new_id(),
            case_id=case_id,
            event_type=event_type,
            actor_type=actor_type,
            actor_id=actor_id,
            payload=freeze_payload(payload),
            occurred_at=utc_now(),
            request_id=request_id,
        )
        self._events.append(event)
        return event

    def events_for_case(self, case_id: str) -> tuple[AuditEvent, ...]:
        return tuple(event for event in self._events if event.case_id == case_id)
