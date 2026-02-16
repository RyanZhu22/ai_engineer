import json
from collections import Counter, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Deque, Dict, List


def _percentile(sorted_values: List[float], p: float) -> float:
    if not sorted_values:
        return 0.0
    if p <= 0:
        return sorted_values[0]
    if p >= 100:
        return sorted_values[-1]

    rank = (len(sorted_values) - 1) * (p / 100.0)
    low = int(rank)
    high = min(low + 1, len(sorted_values) - 1)
    frac = rank - low
    return sorted_values[low] * (1 - frac) + sorted_values[high] * frac


@dataclass
class TelemetryEvent:
    ts: str
    endpoint: str
    status_code: int
    latency_ms: float
    provider: str
    query: str
    top_k: int
    source_docs: List[str]
    error: str


class TelemetryStore:
    def __init__(self, log_path: Path, max_recent: int = 1000) -> None:
        self.log_path = log_path
        self.max_recent = max_recent
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

        self.total_requests = 0
        self.total_errors = 0
        self.endpoint_counts: Counter[str] = Counter()
        self.endpoint_errors: Counter[str] = Counter()
        self.query_counts: Counter[str] = Counter()
        self.source_doc_counts: Counter[str] = Counter()
        self.recent_latencies: Deque[float] = deque(maxlen=max_recent)

    def record(
        self,
        endpoint: str,
        status_code: int,
        latency_ms: float,
        provider: str,
        query: str,
        top_k: int,
        source_docs: List[str] | None = None,
        error: str = "",
    ) -> None:
        source_docs = source_docs or []

        self.total_requests += 1
        self.endpoint_counts[endpoint] += 1
        if status_code >= 400:
            self.total_errors += 1
            self.endpoint_errors[endpoint] += 1
        if query:
            self.query_counts[query.strip()] += 1
        for doc in source_docs:
            self.source_doc_counts[doc] += 1
        self.recent_latencies.append(latency_ms)

        event = TelemetryEvent(
            ts=datetime.now(timezone.utc).isoformat(),
            endpoint=endpoint,
            status_code=status_code,
            latency_ms=round(latency_ms, 3),
            provider=provider,
            query=query,
            top_k=top_k,
            source_docs=source_docs,
            error=error,
        )
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event.__dict__, ensure_ascii=False) + "\n")

    def summary(self) -> Dict[str, object]:
        latencies = sorted(self.recent_latencies)
        avg_latency = (sum(latencies) / len(latencies)) if latencies else 0.0
        error_rate = (self.total_errors / self.total_requests) if self.total_requests else 0.0

        endpoint_stats = []
        for endpoint, count in self.endpoint_counts.items():
            errors = self.endpoint_errors.get(endpoint, 0)
            endpoint_stats.append(
                {
                    "endpoint": endpoint,
                    "requests": count,
                    "errors": errors,
                    "error_rate": round((errors / count) if count else 0.0, 4),
                }
            )
        endpoint_stats.sort(key=lambda x: x["requests"], reverse=True)

        top_queries = [
            {"query": q, "count": c}
            for q, c in self.query_counts.most_common(5)
        ]
        top_source_docs = [
            {"doc_name": d, "count": c}
            for d, c in self.source_doc_counts.most_common(5)
        ]

        return {
            "log_path": str(self.log_path),
            "total_requests": self.total_requests,
            "total_errors": self.total_errors,
            "error_rate": round(error_rate, 4),
            "avg_latency_ms": round(avg_latency, 3),
            "p50_latency_ms": round(_percentile(latencies, 50), 3),
            "p95_latency_ms": round(_percentile(latencies, 95), 3),
            "endpoint_stats": endpoint_stats,
            "top_queries": top_queries,
            "top_source_docs": top_source_docs,
        }
