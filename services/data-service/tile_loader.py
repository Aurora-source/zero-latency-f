from __future__ import annotations

import asyncio
import calendar
import csv
import json
import math
import os
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import httpx
import numpy as np

from api_key_manager import APIKeyManager

try:
    import pandas as pd
except ImportError:
    pd = None

try:
    from scipy.spatial import cKDTree
except ImportError:
    cKDTree = None

DEFAULT_BANGALORE_BBOX = {
    "min_lat": 12.75,
    "max_lat": 13.20,
    "min_lon": 77.35,
    "max_lon": 77.85,
}
CITY_BBOXES: dict[str, dict[str, float]] = {
    "bangalore": DEFAULT_BANGALORE_BBOX,
}
OPENCELLID_MAX_BBOX_AREA_M2 = float(os.getenv("OPENCELLID_MAX_BBOX_AREA_M2", "4000000"))
OPENCELLID_PAGE_LIMIT = 50
TILE_SIDE_METERS = float(os.getenv("TOWER_TILE_SIDE_METERS", "1800"))
TILE_STALE_SECONDS = int(os.getenv("TOWER_TILE_STALE_SECONDS", str(7 * 24 * 60 * 60)))
TILE_ERROR_RETRY_SECONDS = int(os.getenv("TOWER_TILE_ERROR_RETRY_SECONDS", "600"))
DEFAULT_HTTP_TIMEOUT_SECONDS = float(os.getenv("OPENCELLID_HTTP_TIMEOUT_SECONDS", "30"))
LOCAL_TOWER_CSV_PATH = Path(
    os.getenv(
        "LOCAL_TOWER_CSV_PATH",
        str(Path(__file__).resolve().parent / "data" / "towers" / "bangalore_towers.csv"),
    )
)
LOCAL_TOWER_PROVENANCE = os.getenv("LOCAL_TOWER_PROVENANCE", "unknown")
LOCAL_TOWER_SOURCE: dict[str, Any] | None = None
# Local validation must not fall through to external ingestion when data is absent.
LOCAL_DATA_ONLY = os.getenv("LOCAL_DATA_ONLY", "0").strip().lower() in {"1", "true", "yes"}


class QuotaExceededError(RuntimeError):
    pass


@dataclass(frozen=True)
class TileRecord:
    tile_id: str
    city: str
    min_lat: float
    max_lat: float
    min_lon: float
    max_lon: float
    is_cached: bool
    last_updated: str | None
    last_attempt: str | None
    retry_count: int
    last_error: str | None


def _log(logger: Callable[[str], None] | None, message: str) -> None:
    if logger is None:
        print(message)
    else:
        logger(message)


def normalize_tower_provenance(value: Any) -> str:
    normalized = str(value or "").strip().lower().replace(" ", "_").replace("-", "_")
    aliases = {
        "opencellid": "opencellid",
        "open_cell_id": "opencellid",
        "trai": "trai",
        "trai_india": "trai",
        "unknown": "unknown",
    }
    return aliases.get(normalized, "unknown")


def _is_missing_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    try:
        return bool(math.isnan(float(value)))
    except (TypeError, ValueError):
        return False


@contextmanager
def connect_db(db_path: Path):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=30, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
    finally:
        conn.close()


def ensure_schema(db_path: Path) -> None:
    with connect_db(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS tiles (
                tile_id TEXT PRIMARY KEY,
                city TEXT NOT NULL,
                min_lat REAL NOT NULL,
                max_lat REAL NOT NULL,
                min_lon REAL NOT NULL,
                max_lon REAL NOT NULL,
                is_cached INTEGER NOT NULL DEFAULT 0,
                last_updated TIMESTAMP,
                last_attempt TIMESTAMP,
                retry_count INTEGER NOT NULL DEFAULT 0,
                last_error TEXT
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS tiles_rtree USING rtree(
                rowid,
                min_lon,
                max_lon,
                min_lat,
                max_lat
            );

            CREATE TABLE IF NOT EXISTS towers (
                id INTEGER PRIMARY KEY,
                lat REAL NOT NULL,
                lon REAL NOT NULL,
                mcc INTEGER,
                mnc INTEGER,
                lac INTEGER,
                cellid INTEGER,
                radio TEXT,
                range REAL,
                tile_id TEXT,
                UNIQUE (mcc, mnc, lac, cellid, radio, lat, lon)
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS towers_rtree USING rtree(
                id,
                min_lon,
                max_lon,
                min_lat,
                max_lat
            );

            CREATE TABLE IF NOT EXISTS tower_tile_map (
                tower_id INTEGER NOT NULL REFERENCES towers(id) ON DELETE CASCADE,
                tile_id TEXT NOT NULL REFERENCES tiles(tile_id) ON DELETE CASCADE,
                PRIMARY KEY (tower_id, tile_id)
            );

            CREATE TABLE IF NOT EXISTS coverage_tiles (
                tile_id TEXT PRIMARY KEY REFERENCES tiles(tile_id) ON DELETE CASCADE,
                city TEXT NOT NULL,
                has_real_data INTEGER NOT NULL DEFAULT 0,
                source TEXT NOT NULL DEFAULT 'unknown'
            );

            CREATE INDEX IF NOT EXISTS idx_tiles_city_cached ON tiles(city, is_cached, last_updated);
            CREATE INDEX IF NOT EXISTS idx_towers_tile_id ON towers(tile_id);
            CREATE INDEX IF NOT EXISTS idx_tower_tile_map_tile ON tower_tile_map(tile_id);
            CREATE INDEX IF NOT EXISTS idx_coverage_tiles_city ON coverage_tiles(city, has_real_data);
            """
        )
        tile_columns = {
            str(row["name"])
            for row in conn.execute("PRAGMA table_info(tiles)").fetchall()
        }
        if "last_attempt" not in tile_columns:
            conn.execute("ALTER TABLE tiles ADD COLUMN last_attempt TIMESTAMP")
        coverage_columns = {
            str(row["name"])
            for row in conn.execute("PRAGMA table_info(coverage_tiles)").fetchall()
        }
        if "source" not in coverage_columns:
            conn.execute(
                "ALTER TABLE coverage_tiles ADD COLUMN source TEXT NOT NULL DEFAULT 'unknown'"
            )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_tiles_retry ON tiles(city, is_cached, last_attempt)"
        )


def _column_name(candidates: list[str], available: set[str]) -> str | None:
    for candidate in candidates:
        if candidate in available:
            return candidate
    return None


def _load_tower_rows_from_csv(csv_path: Path) -> list[dict[str, Any]]:
    if pd is not None:
        frame = pd.read_csv(csv_path, low_memory=False)
        renamed = {column: str(column).strip().lower() for column in frame.columns}
        frame = frame.rename(columns=renamed)
        columns = set(frame.columns)
        lat_col = _column_name(["lat", "latitude"], columns)
        lon_col = _column_name(["lon", "lng", "longitude"], columns)
        if lat_col is None or lon_col is None:
            raise RuntimeError(f"Tower CSV missing lat/lon columns: {csv_path}")
        radio_col = _column_name(["radio"], columns)
        range_col = _column_name(["range"], columns)
        mcc_col = _column_name(["mcc"], columns)
        mnc_col = _column_name(["mnc", "net"], columns)
        lac_col = _column_name(["lac", "area", "tac", "nid"], columns)
        cellid_col = _column_name(["cellid", "cell"], columns)

        rows: list[dict[str, Any]] = []
        for record in frame.to_dict(orient="records"):
            rows.append(
                {
                    "lat": record.get(lat_col),
                    "lon": record.get(lon_col),
                    "radio": record.get(radio_col) if radio_col else "LTE",
                    "range": record.get(range_col) if range_col else 500.0,
                    "mcc": record.get(mcc_col) if mcc_col else None,
                    "mnc": record.get(mnc_col) if mnc_col else None,
                    "lac": record.get(lac_col) if lac_col else None,
                    "cellid": record.get(cellid_col) if cellid_col else None,
                }
            )
        return rows

    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = {str(name).strip().lower() for name in (reader.fieldnames or [])}
        lat_col = _column_name(["lat", "latitude"], fieldnames)
        lon_col = _column_name(["lon", "lng", "longitude"], fieldnames)
        if lat_col is None or lon_col is None:
            raise RuntimeError(f"Tower CSV missing lat/lon columns: {csv_path}")
        rows = []
        for record in reader:
            lowered = {str(key).strip().lower(): value for key, value in record.items()}
            rows.append(
                {
                    "lat": lowered.get(lat_col),
                    "lon": lowered.get(lon_col),
                    "radio": lowered.get("radio") or "LTE",
                    "range": lowered.get("range") or 500.0,
                    "mcc": lowered.get("mcc"),
                    "mnc": lowered.get("mnc") or lowered.get("net"),
                    "lac": lowered.get("lac") or lowered.get("area") or lowered.get("tac") or lowered.get("nid"),
                    "cellid": lowered.get("cellid") or lowered.get("cell"),
                }
            )
        return rows


def load_local_tower_source(
    csv_path: Path | None = None,
    *,
    source: str | None = None,
    logger: Callable[[str], None] | None = None,
) -> dict[str, Any] | None:
    global LOCAL_TOWER_SOURCE

    source_path = csv_path or LOCAL_TOWER_CSV_PATH
    if not source_path.exists():
        _log(logger, f"[local-towers] CSV not found at {source_path}")
        LOCAL_TOWER_SOURCE = None
        return None

    LOCAL_TOWER_SOURCE = None
    rows = _load_tower_rows_from_csv(source_path)
    bounds = city_bounds("bangalore")
    towers: list[dict[str, Any]] = []
    provenance_source = normalize_tower_provenance(source or LOCAL_TOWER_PROVENANCE)
    for row in rows:
        try:
            lat = float(row.get("lat") or 0.0)
            lon = float(row.get("lon") or 0.0)
            raw_range = row.get("range")
            tower_range = 500.0 if _is_missing_value(raw_range) else float(raw_range)
        except (TypeError, ValueError):
            continue
        if not (bounds["min_lat"] <= lat <= bounds["max_lat"] and bounds["min_lon"] <= lon <= bounds["max_lon"]):
            continue
        towers.append(
            {
                "lat": lat,
                "lon": lon,
                "radio": (
                    "LTE"
                    if _is_missing_value(row.get("radio"))
                    else str(row.get("radio")).upper()
                ),
                "range": tower_range,
                "mcc": _optional_int(row.get("mcc")),
                "mnc": _optional_int(row.get("mnc")),
                "lac": _optional_int(row.get("lac")),
                "cellid": _optional_int(row.get("cellid")),
                "provenance_source": provenance_source,
            }
        )

    towers = dedupe_towers(towers)
    latitudes = np.asarray([tower["lat"] for tower in towers], dtype=np.float32)
    longitudes = np.asarray([tower["lon"] for tower in towers], dtype=np.float32)
    coordinates = np.column_stack((latitudes, longitudes)) if towers else np.empty((0, 2), dtype=np.float32)
    tree = cKDTree(coordinates) if cKDTree is not None and towers else None

    LOCAL_TOWER_SOURCE = {
        "source": provenance_source,
        "path": str(source_path),
        "towers": towers,
        "latitudes": latitudes,
        "longitudes": longitudes,
        "coordinates": coordinates,
        "tree": tree,
        "loaded_at": time.time(),
        "count": len(towers),
    }
    _log(logger, f"[local-towers] loaded {len(towers)} towers")
    return LOCAL_TOWER_SOURCE


def local_tower_source_status() -> dict[str, Any]:
    if LOCAL_TOWER_SOURCE is None:
        return {
            "loaded": False,
            "count": 0,
            "path": str(LOCAL_TOWER_CSV_PATH),
            "source": "unknown",
        }
    return {
        "loaded": True,
        "count": int(LOCAL_TOWER_SOURCE.get("count") or 0),
        "path": str(LOCAL_TOWER_SOURCE.get("path") or LOCAL_TOWER_CSV_PATH),
        "source": normalize_tower_provenance(LOCAL_TOWER_SOURCE.get("source")),
    }


def local_towers_for_bbox(
    min_lat: float,
    min_lon: float,
    max_lat: float,
    max_lon: float,
) -> list[dict[str, Any]] | None:
    if LOCAL_TOWER_SOURCE is None:
        return None

    towers: list[dict[str, Any]] = LOCAL_TOWER_SOURCE["towers"]
    if not towers:
        return []

    latitudes: np.ndarray = LOCAL_TOWER_SOURCE["latitudes"]
    longitudes: np.ndarray = LOCAL_TOWER_SOURCE["longitudes"]
    tree = LOCAL_TOWER_SOURCE.get("tree")

    if tree is not None:
        center_lat = (min_lat + max_lat) / 2.0
        center_lon = (min_lon + max_lon) / 2.0
        radius = math.hypot((max_lat - min_lat) / 2.0, (max_lon - min_lon) / 2.0)
        candidate_indexes = np.asarray(
            tree.query_ball_point([center_lat, center_lon], r=max(radius, 1e-6)),
            dtype=np.int32,
        )
    else:
        candidate_indexes = np.arange(len(towers), dtype=np.int32)

    if candidate_indexes.size == 0:
        return []

    lat_subset = latitudes[candidate_indexes]
    lon_subset = longitudes[candidate_indexes]
    mask = (
        (lat_subset >= min_lat)
        & (lat_subset <= max_lat)
        & (lon_subset >= min_lon)
        & (lon_subset <= max_lon)
    )
    indexes = candidate_indexes[mask]
    return [towers[int(index)] for index in indexes.tolist()]


def city_bounds(city: str) -> dict[str, float]:
    city_slug = city.strip().lower()
    if city_slug not in CITY_BBOXES:
        raise ValueError(f"Unsupported tower-cache city '{city}'")
    return CITY_BBOXES[city_slug]


def coverage_tile_ids_for_bbox(
    city: str,
    min_lat: float,
    min_lon: float,
    max_lat: float,
    max_lon: float,
) -> list[str]:
    """Return bounded grid candidates; callers may apply exact geometry checks."""
    city_slug = city.strip().lower()
    bounds = city_bounds(city_slug)
    avg_lat = (bounds["min_lat"] + bounds["max_lat"]) / 2.0
    lat_step = TILE_SIDE_METERS / 111_000.0
    lon_step = TILE_SIDE_METERS / (
        111_000.0 * max(math.cos(math.radians(avg_lat)), 0.2)
    )
    row_count = max(
        1,
        int(math.ceil((bounds["max_lat"] - bounds["min_lat"]) / lat_step)),
    )
    col_count = max(
        1,
        int(math.ceil((bounds["max_lon"] - bounds["min_lon"]) / lon_step)),
    )
    row_start = max(
        0,
        int(math.floor((min_lat - bounds["min_lat"]) / lat_step)) - 1,
    )
    row_end = min(
        row_count - 1,
        int(math.floor((max_lat - bounds["min_lat"]) / lat_step)) + 1,
    )
    col_start = max(
        0,
        int(math.floor((min_lon - bounds["min_lon"]) / lon_step)) - 1,
    )
    col_end = min(
        col_count - 1,
        int(math.floor((max_lon - bounds["min_lon"]) / lon_step)) + 1,
    )
    if row_start > row_end or col_start > col_end:
        return []
    return [
        f"{city_slug}_{row:03d}_{col:03d}"
        for row in range(row_start, row_end + 1)
        for col in range(col_start, col_end + 1)
    ]


def generate_city_tiles(city: str) -> list[TileRecord]:
    bounds = city_bounds(city)
    avg_lat = (bounds["min_lat"] + bounds["max_lat"]) / 2.0
    lat_step = TILE_SIDE_METERS / 111_000.0
    lon_step = TILE_SIDE_METERS / (111_000.0 * max(math.cos(math.radians(avg_lat)), 0.2))
    tiles: list[TileRecord] = []
    row = 0
    lat_cursor = bounds["min_lat"]
    while lat_cursor < bounds["max_lat"] - 1e-9:
        next_lat = min(lat_cursor + lat_step, bounds["max_lat"])
        col = 0
        lon_cursor = bounds["min_lon"]
        while lon_cursor < bounds["max_lon"] - 1e-9:
            next_lon = min(lon_cursor + lon_step, bounds["max_lon"])
            tile_id = f"{city.strip().lower()}_{row:03d}_{col:03d}"
            tiles.append(
                TileRecord(
                    tile_id=tile_id,
                    city=city.strip().lower(),
                    min_lat=round(lat_cursor, 6),
                    max_lat=round(next_lat, 6),
                    min_lon=round(lon_cursor, 6),
                    max_lon=round(next_lon, 6),
                    is_cached=False,
                    last_updated=None,
                    last_attempt=None,
                    retry_count=0,
                    last_error=None,
                )
            )
            lon_cursor = next_lon
            col += 1
        lat_cursor = next_lat
        row += 1
    return tiles


def ensure_city_tiles(db_path: Path, city: str) -> dict[str, int]:
    ensure_schema(db_path)
    city_slug = city.strip().lower()
    tiles = generate_city_tiles(city_slug)
    with connect_db(db_path) as conn:
        for tile in tiles:
            conn.execute(
                """
                INSERT OR IGNORE INTO tiles (
                    tile_id, city, min_lat, max_lat, min_lon, max_lon, is_cached
                ) VALUES (?, ?, ?, ?, ?, ?, 0)
                """,
                (tile.tile_id, tile.city, tile.min_lat, tile.max_lat, tile.min_lon, tile.max_lon),
            )
            rowid = conn.execute("SELECT rowid FROM tiles WHERE tile_id = ?", (tile.tile_id,)).fetchone()[0]
            conn.execute(
                """
                INSERT OR REPLACE INTO tiles_rtree(rowid, min_lon, max_lon, min_lat, max_lat)
                VALUES (?, ?, ?, ?, ?)
                """,
                (rowid, tile.min_lon, tile.max_lon, tile.min_lat, tile.max_lat),
            )
        cached_tiles = conn.execute(
            "SELECT COUNT(*) FROM tiles WHERE city = ? AND is_cached = 1",
            (city_slug,),
        ).fetchone()[0]
    return {
        "total_tiles": len(tiles),
        "cached_tiles": int(cached_tiles),
    }


def _row_to_tile(row: sqlite3.Row) -> TileRecord:
    return TileRecord(
        tile_id=str(row["tile_id"]),
        city=str(row["city"]),
        min_lat=float(row["min_lat"]),
        max_lat=float(row["max_lat"]),
        min_lon=float(row["min_lon"]),
        max_lon=float(row["max_lon"]),
        is_cached=bool(row["is_cached"]),
        last_updated=row["last_updated"],
        last_attempt=row["last_attempt"],
        retry_count=int(row["retry_count"] or 0),
        last_error=row["last_error"],
    )


def tiles_for_bbox(
    db_path: Path,
    city: str,
    min_lat: float,
    min_lon: float,
    max_lat: float,
    max_lon: float,
    *,
    ensure_tiles: bool = True,
) -> list[TileRecord]:
    if ensure_tiles:
        ensure_city_tiles(db_path, city)
    city_slug = city.strip().lower()
    with connect_db(db_path) as conn:
        rows = conn.execute(
            """
            SELECT t.rowid AS rowid, t.*
            FROM tiles AS t
            JOIN tiles_rtree AS r
              ON t.rowid = r.rowid
            WHERE t.city = ?
              AND r.max_lon >= ?
              AND r.min_lon <= ?
              AND r.max_lat >= ?
              AND r.min_lat <= ?
            ORDER BY t.tile_id
            """,
            (city_slug, min_lon, max_lon, min_lat, max_lat),
        ).fetchall()
    return [_row_to_tile(row) for row in rows]


def cache_status(db_path: Path, city: str = "bangalore") -> dict[str, int | float | str]:
    summary = ensure_city_tiles(db_path, city)
    total_tiles = int(summary["total_tiles"])
    fresh_cutoff = int(time.time() - TILE_STALE_SECONDS)
    with connect_db(db_path) as conn:
        cached_row = conn.execute(
            """
            SELECT COUNT(*) FROM tiles
            WHERE city = ? AND is_cached = 1 AND last_updated IS NOT NULL
              AND CAST(strftime('%s', last_updated) AS INTEGER) >= ?
            """,
            (city.strip().lower(), fresh_cutoff),
        ).fetchone()
        coverage_row = conn.execute(
            """
            SELECT COUNT(*)
            FROM coverage_tiles AS coverage
            JOIN tiles AS tile ON tile.tile_id = coverage.tile_id
            WHERE coverage.city = ? AND coverage.has_real_data = 1
              AND coverage.source IN ('opencellid', 'trai')
              AND tile.is_cached = 1 AND tile.last_updated IS NOT NULL
              AND CAST(strftime('%s', tile.last_updated) AS INTEGER) >= ?
            """,
            (city.strip().lower(), fresh_cutoff),
        ).fetchone()
    cached_tiles = int(cached_row[0]) if cached_row is not None else 0
    remaining_tiles = max(total_tiles - cached_tiles, 0)
    percent_complete = round((cached_tiles / max(total_tiles, 1)) * 100.0, 1)
    real_coverage_tiles = int(coverage_row[0]) if coverage_row is not None else 0
    real_coverage_percent = round((real_coverage_tiles / max(total_tiles, 1)) * 100.0, 1)
    return {
        "city": city.strip().lower(),
        "total_tiles": total_tiles,
        "cached_tiles": cached_tiles,
        "remaining_tiles": remaining_tiles,
        "percent_complete": percent_complete,
        "real_coverage_tiles": real_coverage_tiles,
        "real_coverage_percent": real_coverage_percent,
    }


def fresh_covered_tile_ids(db_path: Path, city: str = "bangalore") -> list[str]:
    ensure_city_tiles(db_path, city)
    fresh_cutoff = int(time.time() - TILE_STALE_SECONDS)
    with connect_db(db_path) as conn:
        rows = conn.execute(
            """
            SELECT tile.tile_id
            FROM tiles AS tile
            JOIN coverage_tiles AS coverage ON coverage.tile_id = tile.tile_id
            WHERE tile.city = ? AND coverage.has_real_data = 1
              AND tile.is_cached = 1 AND tile.last_updated IS NOT NULL
              AND CAST(strftime('%s', tile.last_updated) AS INTEGER) >= ?
            ORDER BY tile.tile_id
            """,
            (city.strip().lower(), fresh_cutoff),
        ).fetchall()
    return [str(row[0]) for row in rows]


def stale_tile_ids(db_path: Path, city: str, *, limit: int | None = None) -> list[str]:
    ensure_city_tiles(db_path, city)
    city_slug = city.strip().lower()
    stale_cutoff = time.time() - TILE_STALE_SECONDS
    retry_cutoff = time.time() - TILE_ERROR_RETRY_SECONDS
    sql = (
        "SELECT tile_id FROM tiles "
        "WHERE city = ? "
        "AND (last_attempt IS NULL OR CAST(strftime('%s', last_attempt) AS INTEGER) < ?) "
        "AND (is_cached = 0 OR last_updated IS NULL "
        "     OR CAST(strftime('%s', last_updated) AS INTEGER) < ?) "
        "ORDER BY is_cached ASC, COALESCE(last_attempt, last_updated, '') ASC, "
        "retry_count ASC, tile_id ASC"
    )
    params: list[Any] = [city_slug, int(retry_cutoff), int(stale_cutoff)]
    if limit is not None:
        sql += " LIMIT ?"
        params.append(int(limit))
    with connect_db(db_path) as conn:
        return [str(row[0]) for row in conn.execute(sql, params).fetchall()]


def tile_bounds(db_path: Path, tile_id: str) -> TileRecord | None:
    with connect_db(db_path) as conn:
        row = conn.execute("SELECT * FROM tiles WHERE tile_id = ?", (tile_id,)).fetchone()
    if row is None:
        return None
    return _row_to_tile(row)


def cached_towers_for_bbox(
    db_path: Path,
    city: str,
    min_lat: float,
    min_lon: float,
    max_lat: float,
    max_lon: float,
    *,
    ensure_tiles: bool = True,
) -> tuple[list[dict[str, Any]], list[str], set[str], list[TileRecord]]:
    query_tiles = tiles_for_bbox(
        db_path,
        city,
        min_lat,
        min_lon,
        max_lat,
        max_lon,
        ensure_tiles=ensure_tiles,
    )
    cutoff = time.time() - TILE_STALE_SECONDS
    tile_ids = [tile.tile_id for tile in query_tiles]
    coverage_rows: list[sqlite3.Row] = []
    if tile_ids:
        placeholders = ",".join("?" for _ in tile_ids)
        with connect_db(db_path) as conn:
            coverage_rows = conn.execute(
                f"""
                SELECT tile_id, has_real_data
                FROM coverage_tiles
                WHERE tile_id IN ({placeholders})
                """,
                tile_ids,
            ).fetchall()
    covered_tile_ids = {
        str(row["tile_id"])
        for row in coverage_rows
        if int(row["has_real_data"] or 0) == 1
    }
    cached_tile_ids = [
        tile.tile_id
        for tile in query_tiles
        if (
            tile.tile_id in covered_tile_ids
            and tile.is_cached
            and tile.last_updated
            and _timestamp_seconds(tile.last_updated) >= cutoff
        )
    ]
    missing_tile_ids = sorted(
        tile.tile_id
        for tile in query_tiles
        if (
            not tile.is_cached
            or tile.tile_id not in covered_tile_ids
            or not tile.last_updated
            or _timestamp_seconds(tile.last_updated) < cutoff
        )
    )

    fresh_covered_tile_ids = set(cached_tile_ids)
    if not cached_tile_ids:
        return [], missing_tile_ids, fresh_covered_tile_ids, query_tiles

    placeholders = ",".join("?" for _ in cached_tile_ids)
    sql = f"""
        SELECT DISTINCT tw.id, tw.lat, tw.lon, tw.mcc, tw.mnc, tw.lac, tw.cellid, tw.radio, tw.range
        FROM towers AS tw
        JOIN tower_tile_map AS map
          ON map.tower_id = tw.id
        JOIN towers_rtree AS r
          ON r.id = tw.id
        WHERE map.tile_id IN ({placeholders})
          AND r.max_lon >= ?
          AND r.min_lon <= ?
          AND r.max_lat >= ?
          AND r.min_lat <= ?
    """
    params: list[Any] = [*cached_tile_ids, min_lon, max_lon, min_lat, max_lat]
    with connect_db(db_path) as conn:
        rows = conn.execute(sql, params).fetchall()

    towers = [
        {
            "id": str(row["id"]),
            "lat": float(row["lat"]),
            "lon": float(row["lon"]),
            "mcc": _optional_int(row["mcc"]),
            "mnc": _optional_int(row["mnc"]),
            "lac": _optional_int(row["lac"]),
            "cellid": _optional_int(row["cellid"]),
            "radio": str(row["radio"] or "LTE").upper(),
            "range": float(row["range"] or 500.0),
        }
        for row in rows
    ]
    return towers, missing_tile_ids, fresh_covered_tile_ids, query_tiles


def coverage_sources_for_tiles(
    db_path: Path,
    tile_ids: set[str],
    *,
    ensure_database: bool = True,
) -> dict[str, str]:
    if not tile_ids:
        return {}
    if ensure_database:
        ensure_schema(db_path)
    placeholders = ",".join("?" for _ in tile_ids)
    with connect_db(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT tile_id, source
            FROM coverage_tiles
            WHERE has_real_data = 1 AND tile_id IN ({placeholders})
            """,
            sorted(tile_ids),
        ).fetchall()
    return {
        str(row["tile_id"]): normalize_tower_provenance(row["source"])
        for row in rows
    }


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _timestamp_seconds(value: str | None) -> int:
    if not value:
        return 0
    try:
        return int(calendar.timegm(time.strptime(value, "%Y-%m-%dT%H:%M:%SZ")))
    except ValueError:
        return 0


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _tower_identity(tower: dict[str, Any]) -> tuple[int | None, int | None, int | None, int | None, str, float, float]:
    return (
        _optional_int(tower.get("mcc")),
        _optional_int(tower.get("mnc")),
        _optional_int(tower.get("lac")),
        _optional_int(tower.get("cellid")),
        str(tower.get("radio") or "LTE").upper(),
        round(float(tower.get("lat") or 0.0), 6),
        round(float(tower.get("lon") or 0.0), 6),
    )


def dedupe_towers(towers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[tuple[int | None, int | None, int | None, int | None, str, float, float], dict[str, Any]] = {}
    for tower in towers:
        unique[_tower_identity(tower)] = tower
    return list(unique.values())


def store_tile_towers(
    db_path: Path,
    tile_id: str,
    towers: list[dict[str, Any]],
    *,
    source: str | None = None,
    error_message: str | None = None,
) -> int:
    ensure_schema(db_path)
    unique_towers = dedupe_towers(towers)
    tower_sources = {
        normalize_tower_provenance(
            tower.get("provenance_source") or tower.get("source")
        )
        for tower in unique_towers
    }
    tower_sources.discard("unknown")
    stored_source = normalize_tower_provenance(source)
    if stored_source == "unknown" and len(tower_sources) == 1:
        stored_source = next(iter(tower_sources))
    now_iso = _now_iso()
    with connect_db(db_path) as conn:
        conn.execute("BEGIN")
        try:
            conn.execute("DELETE FROM tower_tile_map WHERE tile_id = ?", (tile_id,))
            for tower in unique_towers:
                lat = round(float(tower.get("lat") or 0.0), 6)
                lon = round(float(tower.get("lon") or 0.0), 6)
                mcc = _optional_int(tower.get("mcc"))
                mnc = _optional_int(tower.get("mnc"))
                lac = _optional_int(tower.get("lac"))
                cellid = _optional_int(tower.get("cellid"))
                radio = str(tower.get("radio") or "LTE").upper()
                tower_range = float(tower.get("range") or 500.0)
                row = conn.execute(
                    """
                    SELECT id FROM towers
                    WHERE mcc IS ? AND mnc IS ? AND lac IS ? AND cellid IS ?
                      AND radio = ? AND lat = ? AND lon = ?
                    """,
                    (
                        mcc,
                        mnc,
                        lac,
                        cellid,
                        radio,
                        lat,
                        lon,
                    ),
                ).fetchone()
                if row is None:
                    cursor = conn.execute(
                        """
                        INSERT INTO towers (
                            lat, lon, mcc, mnc, lac, cellid, radio, range, tile_id
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            lat,
                            lon,
                            mcc,
                            mnc,
                            lac,
                            cellid,
                            radio,
                            tower_range,
                            tile_id,
                        ),
                    )
                    tower_id = int(cursor.lastrowid)
                else:
                    tower_id = int(row["id"])
                    conn.execute(
                        "UPDATE towers SET range = ? WHERE id = ?",
                        (tower_range, tower_id),
                    )
                conn.execute(
                    """
                    INSERT OR IGNORE INTO tower_tile_map (tower_id, tile_id) VALUES (?, ?)
                    """,
                    (tower_id, tile_id),
                )
                conn.execute(
                    """
                    INSERT OR REPLACE INTO towers_rtree (id, min_lon, max_lon, min_lat, max_lat)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        tower_id,
                        lon,
                        lon,
                        lat,
                        lat,
                    ),
                )

            conn.execute(
                """
                DELETE FROM towers_rtree
                WHERE id IN (
                    SELECT t.id
                    FROM towers AS t
                    LEFT JOIN tower_tile_map AS map
                      ON map.tower_id = t.id
                    WHERE map.tower_id IS NULL
                )
                """
            )
            conn.execute(
                """
                DELETE FROM towers
                WHERE id IN (
                    SELECT t.id
                    FROM towers AS t
                    LEFT JOIN tower_tile_map AS map
                      ON map.tower_id = t.id
                    WHERE map.tower_id IS NULL
                )
                """
            )
            conn.execute(
                """
                UPDATE tiles
                SET is_cached = 1, last_updated = ?, last_attempt = ?,
                    last_error = ?, retry_count = 0
                WHERE tile_id = ?
                """,
                (now_iso, now_iso, error_message, tile_id),
            )
            tile_row = conn.execute(
                "SELECT city FROM tiles WHERE tile_id = ?",
                (tile_id,),
            ).fetchone()
            conn.execute(
                """
                INSERT INTO coverage_tiles (tile_id, city, has_real_data, source)
                VALUES (?, ?, 1, ?)
                ON CONFLICT(tile_id) DO UPDATE SET
                    city = excluded.city,
                    has_real_data = excluded.has_real_data,
                    source = excluded.source
                """,
                (
                    tile_id,
                    str(tile_row["city"]) if tile_row is not None else "bangalore",
                    stored_source,
                ),
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    return len(unique_towers)


def tile_coverage_status(db_path: Path, tile_ids: list[str]) -> tuple[set[str], set[str]]:
    ensure_schema(db_path)
    if not tile_ids:
        return set(), set()

    placeholders = ",".join("?" for _ in tile_ids)
    with connect_db(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT tile_id, has_real_data
            FROM coverage_tiles
            WHERE tile_id IN ({placeholders})
            """,
            tile_ids,
        ).fetchall()

    covered = {
        str(row["tile_id"])
        for row in rows
        if int(row["has_real_data"] or 0) == 1
    }
    known = {str(row["tile_id"]) for row in rows}
    return covered, known


def mark_tile_error(db_path: Path, tile_id: str, error_message: str) -> None:
    now_iso = _now_iso()
    with connect_db(db_path) as conn:
        conn.execute(
            """
            UPDATE tiles
            SET last_error = ?, retry_count = retry_count + 1, last_attempt = ?
            WHERE tile_id = ?
            """,
            (error_message[:500], now_iso, tile_id),
        )


async def fetch_bbox_towers_live(
    min_lat: float,
    min_lon: float,
    max_lat: float,
    max_lon: float,
    *,
    token: str = "",
    key_manager: APIKeyManager | None = None,
    timeout_seconds: float = DEFAULT_HTTP_TIMEOUT_SECONDS,
    logger: Callable[[str], None] | None = None,
    stop_event: Any | None = None,
) -> list[dict[str, Any]]:
    local_towers = local_towers_for_bbox(min_lat, min_lon, max_lat, max_lon)
    if local_towers is not None:
        deduped = dedupe_towers(local_towers)
        _log(logger, f"[local-towers] returned {len(deduped)} towers for bbox")
        return deduped

    if LOCAL_DATA_ONLY:
        return []

    if key_manager is None and not token.strip():
        raise RuntimeError("OpenCellID token is not configured")

    async with httpx.AsyncClient(timeout=timeout_seconds, follow_redirects=True, trust_env=False) as client:
        towers: list[dict[str, Any]] = []
        for index, chunk in enumerate(chunk_bbox(min_lat, min_lon, max_lat, max_lon), start=1):
            towers.extend(
                await fetch_tower_chunk(
                    client,
                    chunk,
                    chunk_number=index,
                    key_manager=key_manager,
                    token=token,
                    logger=logger,
                    stop_event=stop_event,
                )
            )
        deduped = dedupe_towers(towers)
        _log(logger, f"[tower-cache] fetched {len(deduped)} unique towers live")
        return deduped


def fetch_bbox_towers_live_sync(
    min_lat: float,
    min_lon: float,
    max_lat: float,
    max_lon: float,
    *,
    token: str = "",
    key_manager: APIKeyManager | None = None,
    timeout_seconds: float = DEFAULT_HTTP_TIMEOUT_SECONDS,
    logger: Callable[[str], None] | None = None,
    stop_event: Any | None = None,
) -> list[dict[str, Any]]:
    return asyncio.run(
        fetch_bbox_towers_live(
            min_lat,
            min_lon,
            max_lat,
            max_lon,
            token=token,
            key_manager=key_manager,
            timeout_seconds=timeout_seconds,
            logger=logger,
            stop_event=stop_event,
        )
    )


def chunk_bbox(
    min_lat: float,
    min_lon: float,
    max_lat: float,
    max_lon: float,
) -> list[tuple[float, float, float, float]]:
    area_m2 = bbox_area_m2(min_lat, min_lon, max_lat, max_lon)
    if area_m2 <= OPENCELLID_MAX_BBOX_AREA_M2:
        return [(min_lat, min_lon, max_lat, max_lon)]

    avg_lat = (min_lat + max_lat) / 2.0
    lat_step = TILE_SIDE_METERS / 111_000.0
    lon_step = TILE_SIDE_METERS / (111_000.0 * max(math.cos(math.radians(avg_lat)), 0.2))
    chunks: list[tuple[float, float, float, float]] = []
    lat_cursor = min_lat
    while lat_cursor < max_lat - 1e-9:
        next_lat = min(lat_cursor + lat_step, max_lat)
        lon_cursor = min_lon
        while lon_cursor < max_lon - 1e-9:
            next_lon = min(lon_cursor + lon_step, max_lon)
            chunks.append((lat_cursor, lon_cursor, next_lat, next_lon))
            lon_cursor = next_lon
        lat_cursor = next_lat
    return chunks


def bbox_area_m2(min_lat: float, min_lon: float, max_lat: float, max_lon: float) -> float:
    mid_lat = (min_lat + max_lat) / 2.0
    height_m = abs(max_lat - min_lat) * 111_000.0
    width_m = abs(max_lon - min_lon) * 111_000.0 * max(math.cos(math.radians(mid_lat)), 0.2)
    return height_m * width_m


async def fetch_area_size(
    client: httpx.AsyncClient,
    min_lat: float,
    min_lon: float,
    max_lat: float,
    max_lon: float,
    *,
    token: str,
) -> int:
    response = await client.get(
        "https://opencellid.org/cell/getInAreaSize",
        params={
            "token": token,
            "BBOX": f"{min_lat},{min_lon},{max_lat},{max_lon}",
            "format": "json",
        },
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json",
        },
    )
    payload = validated_opencellid_payload(response, request_name="size")
    try:
        return int(payload.get("count", 0))
    except (AttributeError, TypeError, ValueError):
        return 0


async def fetch_area_page(
    client: httpx.AsyncClient,
    min_lat: float,
    min_lon: float,
    max_lat: float,
    max_lon: float,
    *,
    token: str,
    limit: int,
    offset: int,
) -> list[dict[str, Any]]:
    response = await client.get(
        "https://opencellid.org/cell/getInArea",
        params={
            "token": token,
            "BBOX": f"{min_lat},{min_lon},{max_lat},{max_lon}",
            "format": "json",
            "limit": int(limit),
            "offset": int(offset),
        },
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json",
        },
    )
    payload = validated_opencellid_payload(response, request_name="page")
    raw_cells = payload.get("cells", []) if isinstance(payload, dict) else []
    towers: list[dict[str, Any]] = []
    for cell in raw_cells:
        try:
            towers.append(
                {
                    "lat": float(cell.get("lat") or 0.0),
                    "lon": float(cell.get("lon") or 0.0),
                    "mcc": _optional_int(cell.get("mcc")),
                    "mnc": _optional_int(cell.get("mnc")),
                    "lac": _optional_int(cell.get("lac") or cell.get("tac") or cell.get("nid")),
                    "cellid": _optional_int(cell.get("cellid") or cell.get("cell")),
                    "radio": str(cell.get("radio") or "LTE").upper(),
                    "range": float(cell.get("range") or 500.0),
                    "provenance_source": "opencellid",
                }
            )
        except (TypeError, ValueError):
            continue
    return towers


def validated_opencellid_payload(
    response: httpx.Response,
    *,
    request_name: str,
) -> Any:
    remote_message = ""
    try:
        payload = response.json()
        if isinstance(payload, dict):
            remote_message = str(payload.get("error") or payload.get("message") or "")
    except Exception:
        payload = None
        try:
            remote_message = response.text[:500]
        except Exception:
            remote_message = ""

    if response.status_code == 429 or "daily limit exceeded" in remote_message.lower():
        raise QuotaExceededError("OpenCellID quota exceeded")
    if not 200 <= int(response.status_code) < 300:
        raise RuntimeError(
            f"OpenCellID {request_name} request failed with HTTP {response.status_code}"
        )
    if payload is None:
        raise RuntimeError(f"OpenCellID {request_name} response was not valid JSON")
    if isinstance(payload, dict) and (payload.get("error") or payload.get("message")):
        raise RuntimeError(f"OpenCellID {request_name} response reported an error")
    return payload


async def fetch_tower_chunk(
    client: httpx.AsyncClient,
    chunk_bbox: tuple[float, float, float, float],
    *,
    chunk_number: int,
    key_manager: APIKeyManager | None = None,
    token: str = "",
    logger: Callable[[str], None] | None = None,
    stop_event: Any | None = None,
) -> list[dict[str, Any]]:
    chunk_min_lat, chunk_min_lon, chunk_max_lat, chunk_max_lon = chunk_bbox
    local_towers = local_towers_for_bbox(
        chunk_min_lat,
        chunk_min_lon,
        chunk_max_lat,
        chunk_max_lon,
    )
    if local_towers is not None:
        _log(
            logger,
            "[local-towers] fetch chunk "
            f"{chunk_number}: bbox=({chunk_min_lat:.4f},{chunk_min_lon:.4f},{chunk_max_lat:.4f},{chunk_max_lon:.4f}) "
            f"-> {len(local_towers)} towers",
        )
        return local_towers

    if LOCAL_DATA_ONLY:
        return []

    _log(
        logger,
        "[tower-cache] fetch chunk "
        f"{chunk_number}: bbox=({chunk_min_lat:.4f},{chunk_min_lon:.4f},{chunk_max_lat:.4f},{chunk_max_lon:.4f})",
    )
    while True:
        if stop_event is not None and stop_event.is_set():
            raise RuntimeError("OpenCellID fetch interrupted")
        if key_manager is not None:
            if not key_manager.has_available_key():
                if stop_event is None:
                    raise RuntimeError("OpenCellID API keys are temporarily unavailable")
                _log(logger, "[api-key] all keys exhausted — worker waiting")
                if not key_manager.wait_until_available(stop_event):
                    raise RuntimeError("OpenCellID key wait interrupted")
            current_token = key_manager.get_current_key()
        else:
            current_token = token

        try:
            count = await fetch_area_size(
                client,
                chunk_min_lat,
                chunk_min_lon,
                chunk_max_lat,
                chunk_max_lon,
                token=current_token,
            )
            if count <= 0:
                return []
            towers: list[dict[str, Any]] = []
            for offset in range(0, count, OPENCELLID_PAGE_LIMIT):
                if stop_event is not None and stop_event.is_set():
                    raise RuntimeError("OpenCellID fetch interrupted")
                page = await fetch_area_page(
                    client,
                    chunk_min_lat,
                    chunk_min_lon,
                    chunk_max_lat,
                    chunk_max_lon,
                    token=current_token,
                    limit=OPENCELLID_PAGE_LIMIT,
                    offset=offset,
                )
                towers.extend(page)
            return towers
        except QuotaExceededError as exc:
            if key_manager is None:
                raise
            _log(logger, "[api-key] quota message - rotating key")
            key_manager.mark_current_exhausted(reason=str(exc))
            continue
        except RuntimeError as exc:
            message = str(exc).lower()
            if key_manager is not None and "daily limit" in message:
                _log(logger, "[api-key] exception quota hit - rotating key")
                key_manager.mark_current_exhausted(reason=str(exc))
                continue
            raise


def export_schema() -> dict[str, str]:
    return {
        "tiles": (
            "tile_id TEXT PRIMARY KEY, min_lat REAL, max_lat REAL, min_lon REAL, max_lon REAL, "
            "is_cached INTEGER, last_updated TIMESTAMP, last_attempt TIMESTAMP"
        ),
        "towers": "id INTEGER PRIMARY KEY, lat REAL, lon REAL, mcc INTEGER, mnc INTEGER, lac INTEGER, cellid INTEGER, radio TEXT, tile_id TEXT",
        "coverage_tiles": (
            "tile_id TEXT PRIMARY KEY, city TEXT, has_real_data INTEGER, source TEXT"
        ),
        "rtree": "tiles_rtree(rowid, min_lon, max_lon, min_lat, max_lat), towers_rtree(id, min_lon, max_lon, min_lat, max_lat)",
    }
