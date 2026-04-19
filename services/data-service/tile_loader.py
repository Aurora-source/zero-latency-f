from __future__ import annotations

import asyncio
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
        str(Path(__file__).resolve().parent / "data" / "towers" / "towers_bangalore.csv"),
    )
)
LOCAL_TOWER_SOURCE: dict[str, Any] | None = None


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
    retry_count: int
    last_error: str | None


def _log(logger: Callable[[str], None] | None, message: str) -> None:
    if logger is None:
        print(message)
    else:
        logger(message)


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
                has_real_data INTEGER NOT NULL DEFAULT 0
            );

            CREATE INDEX IF NOT EXISTS idx_tiles_city_cached ON tiles(city, is_cached, last_updated);
            CREATE INDEX IF NOT EXISTS idx_towers_tile_id ON towers(tile_id);
            CREATE INDEX IF NOT EXISTS idx_tower_tile_map_tile ON tower_tile_map(tile_id);
            CREATE INDEX IF NOT EXISTS idx_coverage_tiles_city ON coverage_tiles(city, has_real_data);
            """
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
    logger: Callable[[str], None] | None = None,
) -> dict[str, Any] | None:
    global LOCAL_TOWER_SOURCE

    source_path = csv_path or LOCAL_TOWER_CSV_PATH
    if not source_path.exists():
        _log(logger, f"[local-towers] CSV not found at {source_path}")
        LOCAL_TOWER_SOURCE = None
        return None

    rows = _load_tower_rows_from_csv(source_path)
    bounds = city_bounds("bangalore")
    towers: list[dict[str, Any]] = []
    for row in rows:
        try:
            lat = float(row.get("lat") or 0.0)
            lon = float(row.get("lon") or 0.0)
        except (TypeError, ValueError):
            continue
        if not (bounds["min_lat"] <= lat <= bounds["max_lat"] and bounds["min_lon"] <= lon <= bounds["max_lon"]):
            continue
        towers.append(
            {
                "lat": lat,
                "lon": lon,
                "radio": str(row.get("radio") or "LTE").upper(),
                "range": float(row.get("range") or 500.0),
                "mcc": _optional_int(row.get("mcc")),
                "mnc": _optional_int(row.get("mnc")),
                "lac": _optional_int(row.get("lac")),
                "cellid": _optional_int(row.get("cellid")),
            }
        )

    towers = dedupe_towers(towers)
    latitudes = np.asarray([tower["lat"] for tower in towers], dtype=np.float32)
    longitudes = np.asarray([tower["lon"] for tower in towers], dtype=np.float32)
    coordinates = np.column_stack((latitudes, longitudes)) if len(towers) else np.empty((0, 2), dtype=np.float32)
    tree = cKDTree(coordinates) if cKDTree is not None and len(towers) else None

    LOCAL_TOWER_SOURCE = {
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
        return {"loaded": False, "count": 0, "path": str(LOCAL_TOWER_CSV_PATH)}
    return {
        "loaded": True,
        "count": int(LOCAL_TOWER_SOURCE.get("count") or 0),
        "path": str(LOCAL_TOWER_SOURCE.get("path") or LOCAL_TOWER_CSV_PATH),
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
        candidate_indexes = tree.query_ball_point([center_lat, center_lon], r=max(radius, 1e-6))
        candidate_indexes = np.asarray(candidate_indexes, dtype=np.int32)
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
) -> list[TileRecord]:
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
    cached_tiles = int(summary["cached_tiles"])
    remaining_tiles = max(total_tiles - cached_tiles, 0)
    percent_complete = round((cached_tiles / max(total_tiles, 1)) * 100.0, 1)
    with connect_db(db_path) as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM coverage_tiles WHERE city = ? AND has_real_data = 1",
            (city.strip().lower(),),
        ).fetchone()
    real_coverage_tiles = int(row[0]) if row is not None else 0
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


def stale_tile_ids(db_path: Path, city: str, *, limit: int | None = None) -> list[str]:
    ensure_city_tiles(db_path, city)
    city_slug = city.strip().lower()
    stale_cutoff = time.time() - TILE_STALE_SECONDS
    retry_cutoff = time.time() - TILE_ERROR_RETRY_SECONDS
    sql = (
        "SELECT tile_id FROM tiles "
        "WHERE city = ? AND ("
        "  (is_cached = 0 AND (last_updated IS NULL OR CAST(strftime('%s', last_updated) AS INTEGER) < ?))"
        "  OR "
        "  (is_cached = 1 AND (last_updated IS NULL OR CAST(strftime('%s', last_updated) AS INTEGER) < ?))"
        ") "
        "ORDER BY is_cached ASC, COALESCE(last_updated, '') ASC, retry_count ASC, tile_id ASC"
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
) -> tuple[list[dict[str, Any]], list[str], set[str], list[TileRecord]]:
    query_tiles = tiles_for_bbox(db_path, city, min_lat, min_lon, max_lat, max_lon)
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
    stale_or_missing_tile_ids = {
        tile.tile_id
        for tile in query_tiles
        if (
            not tile.is_cached
            or tile.tile_id not in covered_tile_ids
            or not tile.last_updated
            or _timestamp_seconds(tile.last_updated) < cutoff
        )
    }
    missing_tile_ids = sorted(stale_or_missing_tile_ids)

    if not cached_tile_ids:
        return [], missing_tile_ids, covered_tile_ids, query_tiles

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
    return towers, missing_tile_ids, covered_tile_ids, query_tiles


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
        return int(time.mktime(time.strptime(value, "%Y-%m-%dT%H:%M:%SZ")))
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
    error_message: str | None = None,
) -> int:
    ensure_schema(db_path)
    unique_towers = dedupe_towers(towers)
    now_iso = _now_iso()
    with connect_db(db_path) as conn:
        conn.execute("BEGIN")
        try:
            conn.execute("DELETE FROM tower_tile_map WHERE tile_id = ?", (tile_id,))
            for tower in unique_towers:
                lat = round(float(tower.get("lat") or 0.0), 6)
                lon = round(float(tower.get("lon") or 0.0), 6)
                conn.execute(
                    """
                    INSERT OR IGNORE INTO towers (
                        lat, lon, mcc, mnc, lac, cellid, radio, range, tile_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        lat,
                        lon,
                        _optional_int(tower.get("mcc")),
                        _optional_int(tower.get("mnc")),
                        _optional_int(tower.get("lac")),
                        _optional_int(tower.get("cellid")),
                        str(tower.get("radio") or "LTE").upper(),
                        float(tower.get("range") or 500.0),
                        tile_id,
                    ),
                )
                row = conn.execute(
                    """
                    SELECT id FROM towers
                    WHERE mcc IS ? AND mnc IS ? AND lac IS ? AND cellid IS ? AND radio = ? AND lat = ? AND lon = ?
                    """,
                    (
                        _optional_int(tower.get("mcc")),
                        _optional_int(tower.get("mnc")),
                        _optional_int(tower.get("lac")),
                        _optional_int(tower.get("cellid")),
                        str(tower.get("radio") or "LTE").upper(),
                        lat,
                        lon,
                    ),
                ).fetchone()
                if row is None:
                    continue
                tower_id = int(row["id"])
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
                SET is_cached = 1, last_updated = ?, last_error = ?, retry_count = 0
                WHERE tile_id = ?
                """,
                (now_iso, error_message, tile_id),
            )
            tile_row = conn.execute(
                "SELECT city FROM tiles WHERE tile_id = ?",
                (tile_id,),
            ).fetchone()
            conn.execute(
                """
                INSERT INTO coverage_tiles (tile_id, city, has_real_data)
                VALUES (?, ?, ?)
                ON CONFLICT(tile_id) DO UPDATE SET
                    city = excluded.city,
                    has_real_data = excluded.has_real_data
                """,
                (
                    tile_id,
                    str(tile_row["city"]) if tile_row is not None else "bangalore",
                    1 if len(unique_towers) > 0 else 0,
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
            SET last_error = ?, retry_count = retry_count + 1, last_updated = ?
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
    message = extract_error_message(response)
    if response.status_code == 429 or "daily limit exceeded" in message.lower():
        raise QuotaExceededError(message or f"HTTP {response.status_code}")
    response.raise_for_status()
    payload = response.json()
    if isinstance(payload, dict) and "error" in payload:
        if "daily limit exceeded" in str(payload["error"]).lower():
            raise QuotaExceededError(str(payload["error"]))
        raise RuntimeError(f"OpenCellID size error: {payload['error']}")
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
    message = extract_error_message(response)
    if response.status_code == 429 or "daily limit exceeded" in message.lower():
        raise QuotaExceededError(message or f"HTTP {response.status_code}")
    response.raise_for_status()
    payload = response.json()
    if isinstance(payload, dict) and "error" in payload:
        if "daily limit exceeded" in str(payload["error"]).lower():
            raise QuotaExceededError(str(payload["error"]))
        raise RuntimeError(f"OpenCellID page error: {payload['error']}")
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
                }
            )
        except (TypeError, ValueError):
            continue
    return towers


def extract_error_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
        if isinstance(payload, dict):
            return str(payload.get("error") or payload.get("message") or response.text[:200])
    except Exception:
        pass
    return response.text[:200]


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

    _log(
        logger,
        "[tower-cache] fetch chunk "
        f"{chunk_number}: bbox=({chunk_min_lat:.4f},{chunk_min_lon:.4f},{chunk_max_lat:.4f},{chunk_max_lon:.4f})",
    )
    while True:
        if key_manager is not None:
            if key_manager.cooldown_active():
                _log(logger, "[api-key] cooldown active")
                raise RuntimeError("OpenCellID API key cooldown active")
            if not key_manager.has_available_key():
                _log(logger, "[api-key] all keys exhausted - sleeping")
                raise RuntimeError("OpenCellID API key cooldown active")
            try:
                current_token = key_manager.get_current_key()
            except RuntimeError as exc:
                if "cooldown active" in str(exc).lower():
                    _log(logger, "[api-key] cooldown active")
                raise
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
            key_manager.mark_exhausted(reason=str(exc))
            continue
        except RuntimeError as exc:
            message = str(exc).lower()
            if key_manager is not None and "daily limit" in message:
                _log(logger, "[api-key] exception quota hit - rotating key")
                key_manager.mark_exhausted(reason=str(exc))
                continue
            raise


def export_schema() -> dict[str, str]:
    return {
        "tiles": (
            "tile_id TEXT PRIMARY KEY, min_lat REAL, max_lat REAL, min_lon REAL, max_lon REAL, "
            "is_cached INTEGER, last_updated TIMESTAMP"
        ),
        "towers": "id INTEGER PRIMARY KEY, lat REAL, lon REAL, mcc INTEGER, mnc INTEGER, lac INTEGER, cellid INTEGER, radio TEXT, tile_id TEXT",
        "coverage_tiles": "tile_id TEXT PRIMARY KEY, city TEXT, has_real_data INTEGER",
        "rtree": "tiles_rtree(rowid, min_lon, max_lon, min_lat, max_lat), towers_rtree(id, min_lon, max_lon, min_lat, max_lat)",
    }
