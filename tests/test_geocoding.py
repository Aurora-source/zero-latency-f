import asyncio
from pathlib import Path
import runpy

from fastapi import HTTPException
import httpx
import pytest


@pytest.fixture
def geocoder(monkeypatch):
    namespace = runpy.run_path(str(Path(__file__).resolve().parents[1] / "services/data-service/geocoding.py"))
    namespace = namespace["search_place"].__globals__
    async def immediate_sleep(delay):
        return None
    monkeypatch.setattr(namespace["asyncio"], "sleep", immediate_sleep)
    return namespace


def client_for(geocoder, monkeypatch, handler):
    original = httpx.AsyncClient
    def factory(**kwargs):
        assert kwargs["trust_env"] is False
        assert kwargs["timeout"] == 10
        assert "zero-latency-f" in kwargs["headers"]["User-Agent"]
        return original(transport=httpx.MockTransport(handler), **kwargs)
    monkeypatch.setattr(geocoder["httpx"], "AsyncClient", factory)


def test_concurrent_identical_place_searches_share_cached_result(geocoder, monkeypatch):
    calls = []
    def handler(request):
        calls.append(request)
        assert request.url.params["bounded"] == "1"
        return httpx.Response(200, json=[{"lat": "12.97", "lon": "77.59"}])
    client_for(geocoder, monkeypatch, handler)
    async def requests():
        return await asyncio.gather(*(geocoder["search_place"]("MG Road Bengaluru") for _ in range(8)))
    results = asyncio.run(requests())
    assert results == [{"coordinates": [12.97, 77.59]}] * 8
    assert len(calls) == 1


@pytest.mark.parametrize("status,body,expected", [(200, [], 404), (403, {}, 503), (200, {}, 503), (200, [{"lat": "nan", "lon": "77"}], 503)])
def test_search_failure_is_explicit_and_does_not_invent_coordinates(geocoder, monkeypatch, status, body, expected):
    client_for(geocoder, monkeypatch, lambda request: httpx.Response(status, json=body))
    with pytest.raises(HTTPException) as error:
        asyncio.run(geocoder["search_place"]("Unknown place"))
    assert error.value.status_code == expected
    assert not geocoder["CACHE"]


def test_geocoder_cache_is_bounded(geocoder, monkeypatch):
    client_for(geocoder, monkeypatch, lambda request: httpx.Response(200, json=[{"lat": "12.97", "lon": "77.59"}]))
    async def requests():
        for index in range(140):
            await geocoder["search_place"](f"place {index}")
    asyncio.run(requests())
    assert len(geocoder["CACHE"]) == 128
    assert "place 0" not in geocoder["CACHE"]


def test_provider_calls_wait_for_one_second_spacing(geocoder, monkeypatch):
    clock = [10.0]
    waits = []
    monkeypatch.setattr(geocoder["time"], "monotonic", lambda: clock[0])
    async def sleep(delay):
        waits.append(delay)
        clock[0] += delay
    monkeypatch.setattr(geocoder["asyncio"], "sleep", sleep)
    client_for(geocoder, monkeypatch, lambda request: httpx.Response(200, json=[{"lat": "12.97", "lon": "77.59"}]))
    async def requests():
        await geocoder["search_place"]("first place")
        await geocoder["search_place"]("second place")
    asyncio.run(requests())
    assert waits == [0, 1]
