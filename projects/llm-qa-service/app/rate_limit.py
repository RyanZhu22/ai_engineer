"""小型进程内限流器。

该实现适合单实例或开发环境；多实例部署应把同一算法迁移到 Redis/API gateway，
否则每个实例都有独立计数器。
"""
import math
import threading
import time
from collections import defaultdict, deque

from starlette.responses import JSONResponse

from .config import get_settings


class SlidingWindowLimiter:
    def __init__(self, clock=None):
        self._clock = clock or time.monotonic
        # ponytail: 进程内 key 数量随来源地址增长；多实例/高流量部署应迁移到 Redis 或网关。
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str, *, limit: int, window_seconds: int) -> tuple[bool, float]:
        now = self._clock()
        cutoff = now - window_seconds
        with self._lock:
            hits = self._hits[key]
            while hits and hits[0] <= cutoff:
                hits.popleft()
            if len(hits) >= limit:
                return False, max(0.0, hits[0] + window_seconds - now)
            hits.append(now)
            return True, 0.0

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


class RateLimitMiddleware:
    """限制登录和高成本请求，不记录或回显凭据。"""

    _login_path = ("POST", "/auth/login")
    _expensive_paths = {"/chat", "/chat/stream", "/agent", "/agent/stream", "/documents/upload"}

    def __init__(self, app):
        self.app = app
        self.limiter = SlidingWindowLimiter()

    @classmethod
    def _group(cls, method: str, path: str) -> str | None:
        if (method, path) == cls._login_path:
            return "login"
        if method == "POST" and path in cls._expensive_paths:
            return "expensive"
        return None

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        settings = get_settings()
        group = self._group(scope.get("method", ""), scope.get("path", ""))
        if not settings.rate_limit_enabled or group is None:
            return await self.app(scope, receive, send)

        client = scope.get("client")
        host = client[0] if client else "unknown"
        key = f"{group}:{host}"
        limit = (
            settings.rate_limit_login_per_window
            if group == "login"
            else settings.rate_limit_llm_per_window
        )
        allowed, retry_after = self.limiter.check(
            key, limit=limit, window_seconds=settings.rate_limit_window_seconds
        )
        if allowed:
            return await self.app(scope, receive, send)

        retry_seconds = max(1, math.ceil(retry_after))
        response = JSONResponse(
            {"detail": "请求过于频繁，请稍后再试"},
            status_code=429,
            headers={
                "Retry-After": str(retry_seconds),
                "X-RateLimit-Limit": str(limit),
            },
        )
        return await response(scope, receive, send)
