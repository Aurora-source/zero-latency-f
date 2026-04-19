from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable


def load_env_file(env_path: Path) -> dict[str, str]:
    if not env_path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("'").strip('"')
    return values


class APIKeyManager:
    def __init__(
        self,
        *,
        env_path: Path,
        state_path: Path,
        logger: Callable[[str], None] = print,
    ) -> None:
        self.env_path = env_path
        self.state_path = state_path
        self.logger = logger
        self._lock = threading.Lock()
        self.keys = self._load_keys()
        self.logger(f"[api-key] loaded {len(self.keys)} API keys")
        self.current_key_index = 0
        self.exhausted_keys: set[int] = set()
        self.last_reset_time = self._utc_day_token()
        self.next_retry_time = 0.0
        self._load_state()

    def _load_keys(self) -> list[str]:
        env_values = load_env_file(self.env_path)
        raw_keys = os.getenv("OPENCELLID_KEYS") or env_values.get("OPENCELLID_KEYS") or ""
        keys = [value.strip() for value in raw_keys.split(",") if value.strip()]
        if keys:
            return keys
        fallback = os.getenv("OPENCELLID_TOKEN") or env_values.get("OPENCELLID_TOKEN") or ""
        return [fallback.strip()] if fallback.strip() else []

    def _utc_day_token(self) -> str:
        return time.strftime("%Y-%m-%d", time.gmtime())

    def _load_state(self) -> None:
        if not self.state_path.exists():
            return
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        except Exception:
            return
        self.current_key_index = int(payload.get("current_key_index", 0) or 0)
        self.exhausted_keys = {int(index) for index in payload.get("exhausted_keys", [])}
        self.last_reset_time = str(payload.get("last_reset_time") or self._utc_day_token())
        self.next_retry_time = float(payload.get("next_retry_time") or 0.0)
        self._reset_if_new_day_locked()

    def _save_state(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "current_key_index": self.current_key_index,
            "exhausted_keys": sorted(self.exhausted_keys),
            "last_reset_time": self.last_reset_time,
            "next_retry_time": self.next_retry_time,
        }
        self.state_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _reset_if_new_day_locked(self) -> None:
        current_day = self._utc_day_token()
        if self.last_reset_time == current_day:
            return
        self.exhausted_keys.clear()
        self.current_key_index = 0
        self.last_reset_time = current_day
        self.next_retry_time = 0.0
        self._save_state()
        self.logger("[api-key] daily reset applied")

    def _first_available_index_locked(self) -> int | None:
        if not self.keys:
            return None
        for offset in range(len(self.keys)):
            index = (self.current_key_index + offset) % len(self.keys)
            if index not in self.exhausted_keys:
                return index
        return None

    def get_current_key(self) -> str:
        with self._lock:
            self._reset_if_new_day_locked()
            if not self.keys:
                raise RuntimeError("No OpenCellID API keys configured")
            if self.cooldown_active_locked():
                raise RuntimeError("OpenCellID API key cooldown active")
            next_index = self._first_available_index_locked()
            if next_index is None:
                raise RuntimeError("All OpenCellID API keys are exhausted")
            self.current_key_index = next_index
            self._save_state()
            self.logger(f"[api-key] using key {self.current_key_index + 1}")
            return self.keys[self.current_key_index]

    def mark_current_exhausted(self, *, reason: str = "") -> None:
        with self._lock:
            if not self.keys:
                return
            exhausted_index = self.current_key_index
            self.exhausted_keys.add(exhausted_index)
            next_index = self._first_available_index_locked()
            if next_index is None:
                self.next_retry_time = time.time() + self.seconds_until_next_utc_midnight()
                self._save_state()
                self.logger("[api-key] all keys exhausted - sleeping")
                return
            self.next_retry_time = 0.0
            self.current_key_index = next_index
            self._save_state()
            self.logger(
                f"[api-key] switching to key {self.current_key_index + 1}"
                + (f" ({reason})" if reason else "")
            )

    def mark_exhausted(self, *, reason: str = "") -> None:
        self.mark_current_exhausted(reason=reason)

    def has_available_key(self) -> bool:
        with self._lock:
            self._reset_if_new_day_locked()
            if self.cooldown_active_locked():
                return False
            return self._first_available_index_locked() is not None

    def cooldown_active_locked(self) -> bool:
        return bool(self.next_retry_time and time.time() < self.next_retry_time)

    def cooldown_active(self) -> bool:
        with self._lock:
            self._reset_if_new_day_locked()
            return self.cooldown_active_locked()

    def seconds_until_retry(self) -> int:
        with self._lock:
            self._reset_if_new_day_locked()
            if not self.cooldown_active_locked():
                return 0
            return max(int(self.next_retry_time - time.time()), 1)

    def wait_until_available(self, stop_event: threading.Event | None = None) -> bool:
        while True:
            with self._lock:
                self._reset_if_new_day_locked()
                if self._first_available_index_locked() is not None:
                    return True
                seconds = self.seconds_until_next_utc_midnight()
            wait_seconds = min(max(seconds, 1), 60)
            if stop_event is not None and stop_event.wait(wait_seconds):
                return False
            if stop_event is None:
                time.sleep(wait_seconds)

    def seconds_until_next_utc_midnight(self) -> int:
        now = datetime.now(timezone.utc)
        next_midnight = datetime.combine(
            (now + timedelta(days=1)).date(),
            datetime.min.time(),
            tzinfo=timezone.utc,
        )
        return max(int((next_midnight - now).total_seconds()), 1)

    def status(self) -> dict[str, int | list[int] | None]:
        with self._lock:
            self._reset_if_new_day_locked()
            active_index = self._first_available_index_locked()
            cooldown_active = self.cooldown_active_locked()
            next_retry_seconds = (
                max(int(self.next_retry_time - time.time()), 1)
                if cooldown_active
                else 0
            )
            return {
                "total_keys": len(self.keys),
                "active_key": (active_index + 1) if active_index is not None else None,
                "exhausted_keys": [index + 1 for index in sorted(self.exhausted_keys)],
                "remaining_keys": len(self.keys) - len(self.exhausted_keys),
                "cooldown_active": cooldown_active,
                "next_retry_seconds": next_retry_seconds,
            }

    def is_quota_error(self, status_code: int, message: str) -> bool:
        lowered = message.lower()
        return status_code == 429 or "daily limit exceeded" in lowered
