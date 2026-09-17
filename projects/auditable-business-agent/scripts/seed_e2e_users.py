from __future__ import annotations

import os

from app.auth import hash_password
from app.db import build_session_factory
from app.models import UserRole
from app.repositories import SqlAlchemyUserRepository


def _setting(name: str, default: str) -> str:
    return os.getenv(name, default)


def _ensure_user(repository: SqlAlchemyUserRepository, *, username: str, password: str, role: UserRole) -> None:
    existing = repository.get_by_username(username)
    if existing is None:
        repository.create(username=username, password_hash=hash_password(password), role=role.value)
        return
    if existing.role != role:
        raise SystemExit(f"E2E username {username} already has role {existing.role.value}")
    repository.set_password(username=username, password_hash=hash_password(password))


def main() -> None:
    repository = SqlAlchemyUserRepository(build_session_factory())
    _ensure_user(
        repository,
        username=_setting("E2E_CUSTOMER_SERVICE_USERNAME", "e2e-agent"),
        password=_setting("E2E_CUSTOMER_SERVICE_PASSWORD", "customer-service-password"),
        role=UserRole.CUSTOMER_SERVICE,
    )
    _ensure_user(
        repository,
        username=_setting("E2E_APPROVER_USERNAME", "e2e-approver"),
        password=_setting("E2E_APPROVER_PASSWORD", "approver-password-123"),
        role=UserRole.APPROVER,
    )
    print("E2E users are ready.")


if __name__ == "__main__":
    main()
