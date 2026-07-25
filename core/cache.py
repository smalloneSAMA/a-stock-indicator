"""
Simple JSON file-based cache for minimizing HTTP requests.
"""

import json
import os
import time
from pathlib import Path
from threading import Lock


class Cache:
    """File-based JSON cache with TTL support."""

    def __init__(self, namespace: str = "default"):
        cache_dir = Path.home() / ".a_stock_indicator" / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        self._path = cache_dir / f"{namespace}.json"
        self._lock = Lock()
        self._data: dict = self._load()

    def _load(self) -> dict:
        if self._path.exists():
            try:
                return json.loads(self._path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return {}
        return {}

    def _save(self):
        with self._lock:
            self._path.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    def get(self, key: str):
        """Get cached value. Returns None if missing or expired."""
        entry = self._data.get(key)
        if entry is None:
            return None
        if isinstance(entry, dict) and "expires_at" in entry:
            if time.time() > entry["expires_at"]:
                return None
            return entry.get("value")
        return entry

    def set(self, key: str, value, ttl: int = 0):
        """Set cache. ttl=0 means no expiration (until overwritten)."""
        if ttl > 0:
            self._data[key] = {"value": value, "expires_at": time.time() + ttl}
        else:
            self._data[key] = value
        self._save()

    def has(self, key: str) -> bool:
        return self.get(key) is not None

    def delete(self, key: str):
        if key in self._data:
            del self._data[key]
            self._save()

    def clear(self):
        self._data = {}
        self._save()
