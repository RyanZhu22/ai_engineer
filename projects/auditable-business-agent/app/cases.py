from __future__ import annotations

from app.models import SupportRequest


class InMemoryCaseStore:
    """P0 storage adapter retained for isolated domain tests."""

    def __init__(self) -> None:
        self._cases: dict[str, SupportRequest] = {}

    def save(self, request: SupportRequest) -> None:
        existing = self._cases.get(request.case_id)
        if existing is not None and existing != request:
            raise ValueError("Case ID already exists with different request data")
        self._cases[request.case_id] = request

    def get(self, case_id: str) -> SupportRequest | None:
        return self._cases.get(case_id)
