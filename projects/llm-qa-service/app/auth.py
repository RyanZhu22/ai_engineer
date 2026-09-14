"""Password login and revocable opaque bearer sessions (configurable TTL).

Tokens are stored hashed in PostgreSQL; accounts are provisioned by operators.
The ASGI middleware retains identity throughout the SSE response lifecycle.
"""
import asyncio
import hashlib
import hmac
import secrets
import time

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, delete
from starlette.responses import JSONResponse

from .audit import record_audit_event, request_context
from .config import get_settings
from .db import User, LoginSession, get_session_factory
from .security import current_user_id

router = APIRouter(prefix="/auth")


def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
    return f"scrypt${salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, salt, digest = stored.split("$")
        return algorithm == "scrypt" and hmac.compare_digest(hash_password(password, salt), stored)
    except (ValueError, TypeError):
        return False


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class Credentials(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=256)


@router.post("/login")
async def login(body: Credentials, request: Request):
    user_id: str | None = None
    token: str | None = None
    session_ttl = get_settings().session_ttl_seconds
    async with get_session_factory()() as session:
        user = (await session.execute(select(User).where(User.username == body.username))).scalar_one_or_none()
        # Same password work for unknown accounts to reduce username timing leaks.
        stored = user.password_hash if user else hash_password("invalid", "00" * 16)
        valid = await asyncio.to_thread(verify_password, body.password, stored)
        if user and valid and user.active:
            token = secrets.token_urlsafe(32)
            user_id = user.id
            session.add(
                LoginSession(
                    token_hash=token_hash(token),
                    user_id=user.id,
                    expires_at=time.time() + session_ttl,
                )
            )
            await session.commit()

    context = request_context(request)
    if user_id is None or token is None:
        await record_audit_event(
            "auth.login.failure",
            success=False,
            request_id=context["request_id"],
            ip_address=context["ip_address"],
        )
        raise HTTPException(401, "用户名或密码错误")

    await record_audit_event(
        "auth.login.success",
        user_id=user_id,
        request_id=context["request_id"],
        ip_address=context["ip_address"],
    )
    return JSONResponse(
        {
            "access_token": token,
            "token_type": "bearer",
            "expires_in": session_ttl,
        },
        headers={"Cache-Control": "no-store"},
    )


@router.get("/me")
async def me(request: Request):
    return request.state.identity


@router.post("/logout")
async def logout(request: Request):
    async with get_session_factory()() as session:
        await session.execute(delete(LoginSession).where(LoginSession.token_hash == request.state.token_hash))
        await session.commit()
    context = request_context(request)
    await record_audit_event(
        "auth.logout",
        user_id=context["user_id"],
        request_id=context["request_id"],
        ip_address=context["ip_address"],
    )
    return {"logged_out": True}


def require_mcp(request: Request, enabled: bool):
    if enabled and not request.state.identity["can_use_mcp"]:
        raise HTTPException(403, "当前账号未获 MCP 工具权限")


class AuthenticationMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path = scope["path"]
        if path in {"/", "/health", "/metrics", "/auth/login", "/docs", "/openapi.json", "/redoc"} or path.startswith("/static/"):
            return await self.app(scope, receive, send)
        request = Request(scope)
        scheme, _, token = request.headers.get("authorization", "").partition(" ")
        if scheme.lower() != "bearer" or not token or len(token) > 256:
            return await JSONResponse({"detail": "请先登录"}, 401, headers={"WWW-Authenticate": "Bearer"})(scope, receive, send)
        async with get_session_factory()() as session:
            user = (await session.execute(select(User).join(LoginSession, LoginSession.user_id == User.id).where(
                LoginSession.token_hash == token_hash(token), LoginSession.expires_at > time.time(), User.active.is_(True)
            ))).scalar_one_or_none()
        if user is None:
            return await JSONResponse({"detail": "登录已失效"}, 401)(scope, receive, send)
        scope.setdefault("state", {})["identity"] = {"id": user.id, "username": user.username, "can_use_mcp": user.can_use_mcp}
        scope["state"]["token_hash"] = token_hash(token)
        context_token = current_user_id.set(user.id)
        try:
            await self.app(scope, receive, send)
        finally:
            current_user_id.reset(context_token)
