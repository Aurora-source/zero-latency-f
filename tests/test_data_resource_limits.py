"""Retention limits must not change a corridor's returned towers/provenance."""
import asyncio
from unittest.mock import patch

import pytest

from test_data_concurrency import load_data_service


@pytest.fixture
def data():
    namespace = load_data_service()["cache_corridor_towers"].__globals__
    namespace["CORRIDOR_CACHE"] = {}
    namespace["CORRIDOR_CACHE_MAX_ENTRIES"] = 2
    namespace["CORRIDOR_CACHE_MAX_TOWERS"] = 3
    return namespace


def test_many_distinct_corridors_have_bounded_retention(data):
    for index in range(20):
        data["cache_corridor_towers"]((index, 0, index + 1, 1), [{"id": index}], "unknown")
    assert len(data["CORRIDOR_CACHE"]) == 2
    assert sum(len(entry[0]) for entry in data["CORRIDOR_CACHE"].values()) <= 3
    assert all(entry[3] == "unknown" for entry in data["CORRIDOR_CACHE"].values())


def test_tower_budget_evicts_before_entry_limit(data):
    first, second = (0, 0, 1, 1), (1, 1, 2, 2)
    data["cache_corridor_towers"](first, [{"id": 1}, {"id": 2}], "unknown")
    data["cache_corridor_towers"](second, [{"id": 3}, {"id": 4}], "unknown")
    assert first not in data["CORRIDOR_CACHE"]
    assert len(data["CORRIDOR_CACHE"][second][0]) == 2


def test_expired_corridors_are_removed_without_revisiting_them(data):
    first, second = (0, 0, 1, 1), (1, 1, 2, 2)
    with patch.object(data["time"], "time", return_value=1000):
        data["cache_corridor_towers"](first, [{"id": 1}], "unknown")
    with patch.object(data["time"], "time", return_value=1600):
        data["cache_corridor_towers"](second, [{"id": 2}], "unknown")
    assert first not in data["CORRIDOR_CACHE"]
    assert second in data["CORRIDOR_CACHE"]


def test_oversized_uncached_corridor_still_returns_all_towers_and_metadata(data):
    towers = [{"id": index} for index in range(4)]
    metadata = {"source": "unknown", "real_data_coverage_percent": 0}

    async def fetch(*args):
        return towers

    with patch.dict(data, {
        "cached_towers_for_bbox": lambda *args: ([], ["missing"], set(), []),
        "queue_missing_tower_tiles": lambda *args: 0,
        "live_tower_fetch_available": lambda: True,
        "fetch_towers_for_corridor": fetch,
        "tower_provenance_source": lambda: "unknown",
        "corridor_coverage_metadata": lambda *args, **kwargs: metadata,
    }):
        returned, _, coverage = asyncio.run(data["_fetch_towers_cached"](12.97, 77.59, 12.98, 77.60))
    assert returned is towers
    assert coverage == metadata
    assert data["CORRIDOR_CACHE"] == {}
