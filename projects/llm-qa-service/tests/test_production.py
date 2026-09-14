"""P1 生产化能力：清空历史、审计、限流、观测和维护命令。"""
import asyncio
import hashlib
import time
import uuid
from functools import partial

import pytest
from sqlalchemy import select

from app.audit import AuditLog
from app.db import LoginSession, _apply_vector_session_defaults, get_session_factory
from app.maintenance import cleanup_expired
from app.rate_limit import RateLimitMiddleware, SlidingWindowLimiter
from app.config import get_settings
from test_api import client


def _provisioned_account(client):
    username = uuid.uuid4().hex

    async def provision():
        from app.auth import hash_password
        from app.db import User

        async with get_session_factory()() as session:
            session.add(
                User(
                    id=username,
                    username=username,
                    password_hash=hash_password("another-password"),
                )
            )
            await session.commit()

    client.portal.call(provision)
    response = client.post(
        "/auth/login",
        json={"username": username, "password": "another-password"},
    )
    assert response.status_code == 200
    return response.json()["access_token"]


def test_clear_history_is_owner_scoped_and_returns_count(client):
    first_token = client.headers["Authorization"]
    first_conv = client.post("/chat", json={"message": "A 的会话"}).json()["conversation_id"]

    second_token = _provisioned_account(client)
    client.headers["Authorization"] = "Bearer " + second_token
    second_conv = client.post("/chat", json={"message": "B 的会话"}).json()["conversation_id"]
    response = client.delete("/history")
    assert response.status_code == 200
    assert response.json()["deleted_count"] == 1
    assert client.get("/history").json()["conversations"] == []
    assert client.get(f"/history/{first_conv}").status_code == 404

    client.headers["Authorization"] = first_token
    assert client.get(f"/history/{first_conv}").status_code == 200
    assert client.get(f"/history/{second_conv}").status_code == 404
    assert client.delete("/history").json()["deleted_count"] == 1


def test_audit_event_and_request_id_are_recorded(client):
    response = client.get("/health", headers={"X-Request-ID": "p1-test-request"})
    assert response.status_code == 200
    assert response.headers["x-request-id"] == "p1-test-request"

    client.post("/auth/login", json={"username": "missing", "password": "wrong"})

    async def read_events():
        async with get_session_factory()() as session:
            return (await session.execute(select(AuditLog))).scalars().all()

    events = client.portal.call(read_events)
    assert any(event.event == "auth.login.success" and event.success for event in events)
    assert any(event.event == "auth.login.failure" and not event.success for event in events)
    metrics_text = client.get("/metrics").text
    assert "llmqa_requests_total" in metrics_text


def test_sliding_window_limiter_enforces_window_and_expires_entries():
    current = [100.0]
    limiter = SlidingWindowLimiter(lambda: current[0])
    assert limiter.check("ip", limit=2, window_seconds=60)[0]
    assert limiter.check("ip", limit=2, window_seconds=60)[0]
    allowed, retry_after = limiter.check("ip", limit=2, window_seconds=60)
    assert not allowed
    assert retry_after == 60.0
    current[0] = 161.0
    assert limiter.check("ip", limit=2, window_seconds=60)[0]


def test_vector_session_defaults_roll_back_when_extension_is_missing():
    class Cursor:
        def execute(self, statement):
            raise RuntimeError("vector extension unavailable")

        def close(self):
            pass

    class Connection:
        rolled_back = False

        def cursor(self):
            return Cursor()

        def rollback(self):
            self.rolled_back = True

    connection = Connection()
    _apply_vector_session_defaults(connection, None)
    assert connection.rolled_back


def test_rate_limit_middleware_returns_429(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("RATE_LIMIT_LOGIN_PER_WINDOW", "1")
    monkeypatch.setenv("RATE_LIMIT_WINDOW_SECONDS", "60")
    get_settings.cache_clear()
    messages = []

    async def downstream(scope, receive, send):
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    middleware = RateLimitMiddleware(downstream)
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/auth/login",
        "client": ("198.51.100.10", 1234),
        "headers": [],
    }

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        messages.append(message)

    try:
        asyncio.run(middleware(scope, receive, send))
        asyncio.run(middleware(scope, receive, send))
    finally:
        get_settings.cache_clear()
    assert messages[0]["status"] == 204
    assert messages[2]["status"] == 429
    assert (b"retry-after", b"60") in messages[2]["headers"]


def test_cleanup_removes_expired_sessions_and_old_audit_logs(client):
    user_id = client.get("/auth/me").json()["id"]
    token_hash = hashlib.sha256(uuid.uuid4().hex.encode()).hexdigest()
    now = time.time()

    async def seed():
        async with get_session_factory()() as session:
            session.add(LoginSession(token_hash=token_hash, user_id=user_id, expires_at=now - 1))
            session.add(
                AuditLog(
                    event="test.old",
                    user_id=user_id,
                    success=True,
                    created_at=now - 91 * 86400,
                )
            )
            await session.commit()

    client.portal.call(seed)
    result = client.portal.call(partial(cleanup_expired, now=now, audit_retention_days=90))
    assert result["expired_sessions"] >= 1
    assert result["expired_audit_logs"] >= 1

    async def remaining():
        async with get_session_factory()() as session:
            return await session.get(LoginSession, token_hash)

    assert client.portal.call(remaining) is None
    with pytest.raises(ValueError):
        client.portal.call(partial(cleanup_expired, now=now, audit_retention_days=0))
