"""Explicit place searches only; no automatic reverse lookup or ingestion job."""
import asyncio
from collections import OrderedDict
import math
import time

import httpx
from fastapi import HTTPException

CACHE: OrderedDict[str, tuple[float, dict]] = OrderedDict()
LOCK = asyncio.Lock()
LAST_REQUEST_AT = 0.0


async def search_place(query: str) -> dict:
    global LAST_REQUEST_AT
    key = query.strip().casefold()
    if not key:
        raise HTTPException(422, "Enter a place name or latitude, longitude")
    async with LOCK:
        cached = CACHE.get(key)
        if cached and time.monotonic() - cached[0] < 1800:
            CACHE.move_to_end(key)
            return dict(cached[1])
        await asyncio.sleep(max(0, 1.0 - (time.monotonic() - LAST_REQUEST_AT)))
        LAST_REQUEST_AT = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=10, trust_env=False, headers={"User-Agent": "zero-latency-f/0.2 (interactive local Bengaluru route planner)"}) as client:
                response = await client.get("https://nominatim.openstreetmap.org/search", params={
                    "q": query.strip(), "format": "json", "limit": 1,
                    "countrycodes": "in", "viewbox": "77.4674,13.1425,77.7769,12.8348", "bounded": 1,
                })
                response.raise_for_status()
                records = response.json()
            if not isinstance(records, list):
                raise ValueError("Invalid geocoder response")
            if not records:
                raise HTTPException(404, "Place not found inside Bengaluru coverage. Enter latitude, longitude or pick the map.")
            latitude, longitude = float(records[0]["lat"]), float(records[0]["lon"])
            if not math.isfinite(latitude) or not math.isfinite(longitude) or not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
                raise ValueError("Invalid geocoder coordinates")
        except HTTPException:
            raise
        except (httpx.HTTPError, ValueError, KeyError, TypeError, IndexError) as exc:
            raise HTTPException(503, "Place search unavailable. Enter latitude, longitude or pick the map.") from exc
        result = {"coordinates": [latitude, longitude]}
        CACHE[key] = (time.monotonic(), result)
        CACHE.move_to_end(key)
        while len(CACHE) > 128:
            CACHE.popitem(last=False)
        return dict(result)
