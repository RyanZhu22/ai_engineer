from collections import OrderedDict
from dataclasses import dataclass
from time import time
from typing import Any, Dict, Optional


@dataclass
class CacheItem:
    value: Dict[str, Any]
    expire_at: float


class AskCache:
    def __init__(self, max_items: int = 256, ttl_sec: int = 300) -> None:
        self.max_items = max(1, max_items)
        self.ttl_sec = max(1, ttl_sec)
        self.store: OrderedDict[str, CacheItem] = OrderedDict()
        self.hits = 0
        self.misses = 0
        self.evictions = 0

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        now = time()
        item = self.store.get(key)
        if not item:
            self.misses += 1
            return None
        if item.expire_at < now:
            self.store.pop(key, None)
            self.misses += 1
            return None

        self.store.move_to_end(key)
        self.hits += 1
        return item.value

    def set(self, key: str, value: Dict[str, Any]) -> None:
        expire_at = time() + self.ttl_sec
        self.store[key] = CacheItem(value=value, expire_at=expire_at)
        self.store.move_to_end(key)

        while len(self.store) > self.max_items:
            self.store.popitem(last=False)
            self.evictions += 1

    def stats(self) -> Dict[str, Any]:
        total = self.hits + self.misses
        hit_rate = (self.hits / total) if total else 0.0
        return {
            "enabled": True,
            "max_items": self.max_items,
            "ttl_sec": self.ttl_sec,
            "size": len(self.store),
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": round(hit_rate, 4),
            "evictions": self.evictions,
        }
