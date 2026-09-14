"""基础请求可观测性：request id、延迟/状态计数和安全结构化日志。"""
import json
import logging
import re
import threading
import time
import uuid

from starlette.responses import PlainTextResponse

logger = logging.getLogger("llm_qa.request")
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")


class RequestMetrics:
    def __init__(self):
        self._lock = threading.Lock()
        self._total = 0
        self._status: dict[int, int] = {}
        self._latency_count = 0
        self._latency_sum_ms = 0.0
        self._latency_max_ms = 0.0

    def observe(self, status: int, latency_ms: float) -> None:
        with self._lock:
            self._total += 1
            self._status[status] = self._status.get(status, 0) + 1
            self._latency_count += 1
            self._latency_sum_ms += latency_ms
            self._latency_max_ms = max(self._latency_max_ms, latency_ms)

    def snapshot(self) -> dict:
        with self._lock:
            count = self._latency_count
            return {
                "requests_total": self._total,
                "responses_by_status": dict(sorted(self._status.items())),
                "latency_ms_avg": round(self._latency_sum_ms / count, 3) if count else 0.0,
                "latency_ms_max": round(self._latency_max_ms, 3),
            }

    def prometheus(self) -> str:
        snapshot = self.snapshot()
        lines = [
            "# HELP llmqa_requests_total Total HTTP requests handled by this process.",
            "# TYPE llmqa_requests_total counter",
            f"llmqa_requests_total {snapshot['requests_total']}",
            "# HELP llmqa_response_status_total HTTP responses by status code.",
            "# TYPE llmqa_response_status_total counter",
        ]
        for status, count in snapshot["responses_by_status"].items():
            lines.append(f'llmqa_response_status_total{{status="{status}"}} {count}')
        lines.extend(
            [
                "# HELP llmqa_request_latency_ms_avg Average request latency in milliseconds.",
                "# TYPE llmqa_request_latency_ms_avg gauge",
                f"llmqa_request_latency_ms_avg {snapshot['latency_ms_avg']}",
                "# HELP llmqa_request_latency_ms_max Maximum request latency in milliseconds.",
                "# TYPE llmqa_request_latency_ms_max gauge",
                f"llmqa_request_latency_ms_max {snapshot['latency_ms_max']}",
                "",
            ]
        )
        return "\n".join(lines)


metrics = RequestMetrics()


def _request_id(scope) -> str:
    for name, value in scope.get("headers", []):
        if name.lower() == b"x-request-id":
            candidate = value.decode("ascii", errors="ignore")
            if _REQUEST_ID_RE.fullmatch(candidate):
                return candidate
            break
    return uuid.uuid4().hex


class RequestObservabilityMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        request_id = _request_id(scope)
        scope.setdefault("state", {})["request_id"] = request_id
        started = time.perf_counter()
        status_holder = {"status": 500}

        async def send_with_context(message):
            if message.get("type") == "http.response.start":
                status_holder["status"] = int(message.get("status", 500))
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode("ascii")))
                message = dict(message)
                message["headers"] = headers
            await send(message)

        try:
            return await self.app(scope, receive, send_with_context)
        finally:
            latency_ms = (time.perf_counter() - started) * 1000
            status = status_holder["status"]
            metrics.observe(status, latency_ms)
            identity = scope.get("state", {}).get("identity") or {}
            logger.info(
                json.dumps(
                    {
                        "event": "http_request",
                        "request_id": request_id,
                        "method": scope.get("method"),
                        "path": scope.get("path"),
                        "status": status,
                        "latency_ms": round(latency_ms, 3),
                        "user_id": identity.get("id"),
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            )


def metrics_response() -> PlainTextResponse:
    return PlainTextResponse(metrics.prometheus(), media_type="text/plain; version=0.0.4")
