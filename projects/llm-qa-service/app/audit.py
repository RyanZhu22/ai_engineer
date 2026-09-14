"""安全审计事件写入。

审计只记录事件、结果、请求 ID 和来源地址，不记录密码、token 或请求正文。
写入失败不会阻断业务请求，但会留下结构化日志供排查。
"""
import json
import logging
import time
from typing import Any

from fastapi import Request

from .db import AuditLog, get_session_factory

logger = logging.getLogger(__name__)
MAX_DETAILS_BYTES = 2_000


def request_context(request: Request) -> dict[str, str | None]:
    """提取不会泄露凭据的请求上下文。"""
    state = request.scope.get("state", {})
    identity = state.get("identity") or {}
    client = request.client
    return {
        "user_id": identity.get("id"),
        "request_id": state.get("request_id"),
        "ip_address": client.host if client else None,
    }


def _encode_details(details: dict[str, Any] | None) -> str | None:
    if not details:
        return None
    try:
        encoded = json.dumps(details, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        encoded = json.dumps({"value": str(details)}, ensure_ascii=False)
    raw = encoded.encode("utf-8")
    if len(raw) <= MAX_DETAILS_BYTES:
        return encoded
    # Details are diagnostics only; truncate at a UTF-8 boundary.
    return raw[:MAX_DETAILS_BYTES].decode("utf-8", errors="ignore")


async def record_audit_event(
    event: str,
    *,
    success: bool = True,
    user_id: str | None = None,
    request_id: str | None = None,
    ip_address: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """写入一条审计事件；数据库短暂不可用时不影响主请求。"""
    try:
        async with get_session_factory()() as session:
            session.add(
                AuditLog(
                    event=event[:64],
                    success=success,
                    user_id=user_id,
                    request_id=request_id,
                    ip_address=ip_address,
                    details=_encode_details(details),
                    created_at=time.time(),
                )
            )
            await session.commit()
    except Exception:
        logger.warning("audit_write_failed event=%s", event, exc_info=True)
