from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from api_key_manager import APIKeyManager
from tile_loader import (
    DEFAULT_HTTP_TIMEOUT_SECONDS,
    cache_status,
    ensure_city_tiles,
    fetch_bbox_towers_live_sync,
    mark_tile_error,
    stale_tile_ids,
    store_tile_towers,
    tile_bounds,
)


@dataclass
class TileIngestionResult:
    tile_id: str
    tower_count: int
    status: str
    error: str | None = None


class TowerIngestionWorker:
    def __init__(
        self,
        *,
        db_path: Path,
        city: str,
        key_manager: APIKeyManager | None,
        logger: Callable[[str], None] = print,
        on_tile_ingested: Callable[[str, str, int], None] | None = None,
        request_delay_seconds: float = 3.0,
        request_timeout_seconds: float = DEFAULT_HTTP_TIMEOUT_SECONDS,
    ) -> None:
        self.db_path = db_path
        self.city = city.strip().lower()
        self.key_manager = key_manager
        self.logger = logger
        self.on_tile_ingested = on_tile_ingested
        self.request_delay_seconds = request_delay_seconds
        self.request_timeout_seconds = request_timeout_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._queue: queue.Queue[str] = queue.Queue()
        self._queued_ids: set[str] = set()
        self._lock = threading.Lock()

    def start(self) -> None:
        ensure_city_tiles(self.db_path, self.city)
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name=f"tower-ingestion-{self.city}", daemon=True)
        self._thread.start()
        self.logger(f"[tower-cache] background worker started for {self.city}")

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=2.0)

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def enqueue_tiles(self, tile_ids: list[str]) -> int:
        queued = 0
        with self._lock:
            for tile_id in tile_ids:
                if tile_id in self._queued_ids:
                    continue
                self._queued_ids.add(tile_id)
                self._queue.put(tile_id)
                queued += 1
        if queued:
            self.logger(f"[tower-cache] queued {queued} tile(s) for {self.city}")
        return queued

    def status(self) -> dict[str, int | float | str]:
        payload = cache_status(self.db_path, self.city)
        payload["queued_tiles"] = int(self._queue.qsize())
        return payload

    def _next_tile(self) -> str | None:
        try:
            return self._queue.get_nowait()
        except queue.Empty:
            stale = stale_tile_ids(self.db_path, self.city, limit=1)
            if stale:
                return stale[0]
        return None

    def _mark_dequeued(self, tile_id: str) -> None:
        with self._lock:
            self._queued_ids.discard(tile_id)

    def _run(self) -> None:
        while not self._stop.is_set():
            tile_id = self._next_tile()
            if tile_id is None:
                self._stop.wait(2.0)
                continue
            if self.key_manager is not None:
                if self.key_manager.cooldown_active():
                    self.logger("[api-key] cooldown active")
                    self._stop.wait(min(max(self.key_manager.seconds_until_retry(), 1), 30))
                    continue
                if not self.key_manager.has_available_key():
                    self._stop.wait(2.0)
                    continue
            self._mark_dequeued(tile_id)
            result = self._fetch_and_store_tile(tile_id)
            if result.status == "ok" and self.on_tile_ingested is not None:
                try:
                    self.on_tile_ingested(self.city, tile_id, result.tower_count)
                except Exception as exc:
                    self.logger(f"[tower-cache] adaptive sync failed for {tile_id}: {exc}")
            if self.request_delay_seconds > 0:
                self._stop.wait(self.request_delay_seconds)

    def _fetch_and_store_tile(self, tile_id: str) -> TileIngestionResult:
        tile = tile_bounds(self.db_path, tile_id)
        if tile is None:
            return TileIngestionResult(tile_id=tile_id, tower_count=0, status="error", error="tile not found")
        try:
            self.logger(
                f"[tile-worker] fetching tile {tile_id} "
                f"bbox=({tile.min_lat:.4f},{tile.min_lon:.4f},{tile.max_lat:.4f},{tile.max_lon:.4f})"
            )
            towers = fetch_bbox_towers_live_sync(
                tile.min_lat,
                tile.min_lon,
                tile.max_lat,
                tile.max_lon,
                key_manager=self.key_manager,
                timeout_seconds=self.request_timeout_seconds,
                logger=self.logger,
                stop_event=self._stop,
            )
            tower_count = store_tile_towers(self.db_path, tile_id, towers)
            self.logger(f"[tile-worker] tile stored {tile_id} ({tower_count} towers)")
            return TileIngestionResult(tile_id=tile_id, tower_count=tower_count, status="ok")
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            mark_tile_error(self.db_path, tile_id, message)
            if "Daily limit exceeded" in message or "429" in message:
                self.logger(f"[tile-worker] quota detected for {tile_id}")
            self.logger(f"[tower-cache] fetch failed for {tile_id}: {message}")
            return TileIngestionResult(tile_id=tile_id, tower_count=0, status="error", error=message)
