"""运维维护命令：清理过期登录会话和旧审计记录。

用法：``python -m app.maintenance cleanup-sessions``。
该命令应由受控的 cron/Job 运行，不暴露为业务 API。
"""
import argparse
import asyncio
import time

from sqlalchemy import delete

from .config import get_settings
from .db import AuditLog, LoginSession, close_db, get_session_factory, init_db


async def cleanup_expired(*, now: float | None = None, audit_retention_days: int | None = None) -> dict[str, int]:
    now = time.time() if now is None else now
    retention_days = (
        get_settings().audit_retention_days
        if audit_retention_days is None
        else audit_retention_days
    )
    if retention_days < 1:
        raise ValueError("audit_retention_days 必须大于等于 1")
    audit_cutoff = now - retention_days * 86400
    async with get_session_factory()() as session:
        sessions_result = await session.execute(
            delete(LoginSession).where(LoginSession.expires_at <= now)
        )
        audit_result = await session.execute(
            delete(AuditLog).where(AuditLog.created_at < audit_cutoff)
        )
        await session.commit()
    return {
        "expired_sessions": int(sessions_result.rowcount or 0),
        "expired_audit_logs": int(audit_result.rowcount or 0),
    }


async def _main(args) -> None:
    await init_db()
    try:
        result = await cleanup_expired(audit_retention_days=args.audit_retention_days)
        print(result)
    finally:
        await close_db()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    cleanup = subparsers.add_parser("cleanup-sessions", help="删除过期 bearer session 和旧审计记录")
    cleanup.add_argument(
        "--audit-retention-days",
        type=int,
        default=None,
        help="审计日志保留天数，默认读取 AUDIT_RETENTION_DAYS",
    )
    args = parser.parse_args()
    if args.audit_retention_days is not None and args.audit_retention_days < 1:
        parser.error("--audit-retention-days 必须大于等于 1")
    asyncio.run(_main(args))
