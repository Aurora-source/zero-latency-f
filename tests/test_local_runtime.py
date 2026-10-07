"""Offline startup and legacy provenance checks without real data or networking."""
from __future__ import annotations

import asyncio
import pickle
import runpy
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def data():
    service_dir = str(ROOT / "services/data-service")
    sys.path.insert(0, service_dir)
    try:
        return runpy.run_path(str(Path(service_dir) / "main.py"))["startup_event"].__globals__
    finally:
        sys.path.remove(service_dir)


def test_local_startup_never_constructs_key_manager_or_ingestion_worker(data, monkeypatch, tmp_path):
    forbidden = Mock(side_effect=AssertionError("credentials/ingestion accessed"))
    preload = Mock()
    for name, value in {
        "LOCAL_DATA_ONLY": True, "API_KEY_MANAGER": None, "APIKeyManager": forbidden,
        "TowerIngestionWorker": forbidden, "TOWER_WORKER": None,
        "APP_CACHE_DIR": tmp_path, "GRAPH_CACHE_DIR": tmp_path / "graphs",
        "OSMNX_HTTP_CACHE_DIR": tmp_path / "http", "GRAPH_STATUS": {},
        "SCHEDULER_THREAD": SimpleNamespace(is_alive=lambda: True),
        "load_hotspot_cache": lambda: None, "load_local_towers": lambda: None,
        "initialize_tower_cache": lambda: None, "detect_system_gpu": lambda: None,
        "validate_cupy_runtime": lambda: None, "schedule_preload": preload,
    }.items():
        monkeypatch.setitem(data, name, value)
    data["startup_event"]()
    forbidden.assert_not_called()
    preload.assert_called_once_with("bangalore")


def test_missing_local_graph_does_not_geocode_or_download(data, monkeypatch, tmp_path):
    forbidden = Mock(side_effect=AssertionError("external graph request"))
    for name, value in {
        "LOCAL_DATA_ONLY": True, "GRAPH_CACHE_DIR": tmp_path,
        "OSMNX_HTTP_CACHE_DIR": tmp_path / "http", "load_local_graph_fallback": lambda city: None,
        "geocode_place_boundary": forbidden,
    }.items():
        monkeypatch.setitem(data, name, value)
    with pytest.raises(data["GraphLoadTransientError"], match="LOCAL_DATA_ONLY"):
        data["load_or_fetch_graph"]("bangalore")
    forbidden.assert_not_called()


@pytest.mark.parametrize("local_result", [None, [], [{"lat": 12.97, "lon": 77.59}]])
def test_local_tower_queries_cannot_fall_through_to_network(data, monkeypatch, local_result):
    loader = sys.modules["tile_loader"]
    monkeypatch.setattr(loader, "LOCAL_DATA_ONLY", True)
    monkeypatch.setattr(loader, "local_towers_for_bbox", lambda *args: local_result)
    client = Mock(side_effect=AssertionError("network client constructed"))
    monkeypatch.setattr(loader.httpx, "AsyncClient", client)
    result = asyncio.run(loader.fetch_bbox_towers_live(12.9, 77.5, 13.0, 77.6))
    assert len(result) == len(local_result or [])
    result = asyncio.run(loader.fetch_tower_chunk(Mock(), (12.9, 77.5, 13.0, 77.6), chunk_number=1))
    assert len(result) == len(local_result or [])
    client.assert_not_called()


@pytest.mark.parametrize("source,expected", [("unknown", 0.0), ("opencellid", 100.0), ("trai", 100.0)])
def test_local_tower_presence_alone_does_not_establish_real_coverage(data, monkeypatch, source, expected):
    monkeypatch.setitem(data, "coverage_sources_for_tiles", lambda *args: {})
    metadata = data["corridor_coverage_metadata"](
        [{"lat": 12.97, "lon": 77.59}], [], set(), [], live_full_bbox=True, live_source=source,
    )
    assert metadata["real_data_coverage_percent"] == expected
    assert metadata["source"] == source


def test_unknown_corridor_scores_keep_estimates_and_revision_but_zero_real_coverage(data, monkeypatch):
    monkeypatch.setitem(data, "GRAPH_CACHE", {"bangalore": SimpleNamespace(
        graph_revision="graph-a", score_revision="score-a",
    )})

    async def fetch(*args):
        return [{"lat": 12.97, "lon": 77.59}], {}, {"live_full_bbox": True, "source": "unknown"}

    monkeypatch.setitem(data, "fetch_towers_cached", fetch)
    monkeypatch.setitem(data, "compute_scores_from_towers", lambda coords, towers: {edge: 0.8 for edge in coords})
    payload = data["CorridorScoresRequest"](
        city="bangalore", graph_revision="graph-a", score_revision="score-a",
        origin=[12.97, 77.59], destination=[12.98, 77.60], edge_coords={"edge": [12.975, 77.595]},
    )
    result = asyncio.run(data["_calculate_corridor_scores"](payload))
    assert result["scores"] == {"edge": 0.8}
    assert result["edge_sources"] == {"edge": "unknown"}
    assert result["source"] == "unknown"
    assert result["real_data_coverage_percent"] == 0.0
    assert result["graph_revision"] == "graph-a"
    assert result["base_score_revision"] == "score-a"


@pytest.mark.parametrize("sources,expected_source,expected_percent", [
    ({"a": "unknown", "b": "unknown"}, "unknown", 0.0),
    ({"a": "opencellid", "b": "unknown"}, "unknown", 50.0),
    ({}, "ml_synthetic", 0.0),
])
def test_city_coverage_counts_only_provider_backed_scores(data, sources, expected_source, expected_percent):
    state = SimpleNamespace(real_score_sources=sources, segment_lookup={"a": 0, "b": 1}, segments=["a", "b"])
    source, _, percent = data["score_provenance_summary"](state)
    assert (source, percent) == (expected_source, expected_percent)


def test_matching_score_envelope_without_provider_evidence_cannot_claim_real_coverage(data, monkeypatch, tmp_path):
    monkeypatch.setitem(data, "REAL_SCORE_DIR", tmp_path)
    state = SimpleNamespace(graph_revision="graph-a", segments=["a"], segment_lookup={"a": 0})
    payload = {
        "graph_revision": "graph-a", "score_revision": "score-a", "scores": {"a": 0.8},
        "metadata": {"source": "unknown", "real_data_coverage_percent": 100.0},
    }
    with (tmp_path / "bangalore_real_scores.pkl").open("wb") as handle:
        pickle.dump(payload, handle)
    values, metadata = data["load_real_scores"]("bangalore", state)
    assert float(values[0]) == pytest.approx(0.8)
    assert metadata["source"] == "unknown"
    assert metadata["real_data_coverage_percent"] == 0.0
    assert metadata["score_revision"] == "score-a"


def test_legacy_tile_schema_migration_keeps_unknown_provider_and_excludes_real_coverage(data, monkeypatch, tmp_path):
    import sqlite3
    loader = sys.modules["tile_loader"]
    db = tmp_path / "towers.db"
    loader.ensure_city_tiles(db, "bangalore")
    with sqlite3.connect(db) as conn:
        tile_id = conn.execute("SELECT tile_id FROM tiles LIMIT 1").fetchone()[0]
        conn.execute("DROP TABLE coverage_tiles")
        conn.execute("CREATE TABLE coverage_tiles (tile_id TEXT PRIMARY KEY, city TEXT, has_real_data INTEGER)")
        conn.execute("INSERT INTO coverage_tiles VALUES (?, 'bangalore', 1)", (tile_id,))
        conn.execute("UPDATE tiles SET is_cached=1, last_updated=strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE tile_id=?", (tile_id,))
    loader.ensure_schema(db)
    assert loader.coverage_sources_for_tiles(db, {tile_id}) == {tile_id: "unknown"}
    assert loader.cache_status(db)["real_coverage_tiles"] == 0
    monkeypatch.setitem(data, "TOWER_CACHE_DB_PATH", db)
    assert data["safe_cache_status_payload"]()["real_data_coverage_percent"] == 0.0
    assert data["cached_coverage_metadata"]("bangalore") is None
