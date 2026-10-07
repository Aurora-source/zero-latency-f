"""Real gateway smoke checks; start Compose with trusted artifacts first.

Does not start/stop containers, alter inputs, download data, or fake inference.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import time
from urllib import request, error
from urllib.parse import urlsplit


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8080")
    parser.add_argument("--output", type=Path, default=Path(".cache/production-smoke.json"))
    parser.add_argument("--ready-timeout", type=float, default=600)
    args = parser.parse_args()
    if urlsplit(args.url).hostname not in ("127.0.0.1", "localhost", "::1"):
        parser.error("This validation is localhost-only")
    opener = request.build_opener(request.ProxyHandler({}))
    records = []
    def call(path, payload=None):
        started = time.monotonic()
        body = None if payload is None else json.dumps(payload).encode()
        req = request.Request(args.url.rstrip("/") + path, data=body,
                              headers={"Content-Type": "application/json"} if body else {})
        try:
            response = opener.open(req, timeout=90)
        except error.HTTPError as exc:
            response = exc
        except (error.URLError, OSError):
            records.append({"path": path, "status": 0, "elapsed_s": time.monotonic()-started,
                            "body": "Gateway connection unavailable"})
            return 0, {}
        with response:
            raw = response.read()
            result = json.loads(raw) if "json" in response.headers.get("Content-Type", "") else raw.decode()
            records.append({"path": path, "status": response.status, "elapsed_s": time.monotonic()-started, "body": result})
            return response.status, result
    try:
        deadline = time.monotonic() + args.ready_timeout
        while time.monotonic() < deadline:
            if call("/healthz")[0] == 200 and all(call("/api/ready/" + name)[0] == 200 for name in ("prediction", "data", "routing")):
                break
            time.sleep(2)
        else:
            raise RuntimeError("Stack did not become ready within the bounded deadline")
        assert call("/")[0] == 200
        assert call("/inspect-route")[0] == 200  # SPA reload fallback
        assert call("/api/cities")[0] == 200
        status, source = call("/api/scores/source/bangalore")
        assert status == 200 and source["graph_revision"] and source["score_revision"]
        prediction = {"city": "bangalore", "graph_revision": source["graph_revision"], "hour_of_day": 12,
                      "segments": [{"id": "release-probe", "lat": 12.975, "lon": 77.590, "highway": "primary", "length": 100}]}
        status, body = call("/api/predict", prediction)
        assert status == 200 and body["graph_revision"] == source["graph_revision"]
        assert math.isfinite(body["scores"]["release-probe"]) and body["confidence"] is None
        assert call("/api/predict", prediction)[1] == body
        invalid = prediction | {"segments": [{"id": "bad", "lat": 91, "lon": 77}]}
        assert call("/api/predict", invalid)[0] == 422
        route = {"city": "bangalore", "origin": [12.9750564233, 77.5903035618],
                 "destination": [12.9798218, 77.6009173], "vehicle": "car", "mode": "fastest"}
        status, body = call("/api/route", route)
        assert status == 200 and body["graph_revision"] == source["graph_revision"]
        assert body["total_time_min"] > 0 and len(body["path_geojson"]["coordinates"]) > 1
        assert body["real_data_coverage_percent"] == 0  # these inputs have unknown tower provenance
        assert call("/api/route", route | {"origin": [91, 77]})[0] in (400, 422)
        assert call("/api/not-an-application-endpoint")[0] == 404
        print("Gateway, SPA, readiness, real CPU inference, route, and invalid-input checks passed")
    finally:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(records, indent=2) + "\n")


if __name__ == "__main__":
    main()
