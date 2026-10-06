from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import runpy
import threading
from unittest.mock import Mock

import httpx
import numpy as np
import pytest

MAIN = Path(__file__).resolve().parents[1] / "services/prediction-service/main.py"


@pytest.fixture
def prediction(monkeypatch, tmp_path):
    monkeypatch.setenv("MODEL_DIR", str(tmp_path))
    monkeypatch.setenv("ALLOW_MODEL_TRAINING", "0")
    monkeypatch.setenv("PREDICTION_DEVICE", "cpu")
    return runpy.run_path(str(MAIN))["get_model"].__globals__


async def post(prediction, segments):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=prediction["app"]), base_url="http://test", trust_env=False) as client:
        return await client.post("/predict", json={"segments": segments, "graph_revision": "graph-a", "hour_of_day": 14})


def test_missing_model_is_live_not_ready_and_never_trains(prediction, monkeypatch):
    train = Mock(side_effect=AssertionError("Training is forbidden"))
    monkeypatch.setitem(prediction, "generate_synthetic_training_data", train)
    prediction["startup_event"]()
    assert prediction["health"]()["model_ready"] is False
    assert prediction["ready"]().status_code == 503
    assert prediction["MODEL_ERROR"] == "model_unavailable"
    train.assert_not_called()


def test_model_load_is_single_flight_and_failed_start_can_recover(prediction, monkeypatch):
    prediction["startup_event"]()
    model = object()
    load = Mock(return_value=(model, "test"))
    monkeypatch.setitem(prediction, "train_or_load_model", load)
    with ThreadPoolExecutor(max_workers=6) as pool:
        values = list(pool.map(lambda _: prediction["get_model"](), range(12)))
    assert all(value is model for value in values)
    load.assert_called_once()
    prediction["startup_event"]()
    assert prediction["MODEL_ERROR"] is None
    assert prediction["ready"]().status_code == 200


def test_legacy_model_provenance_and_confidence_remain_unknown(prediction, monkeypatch):
    prediction["MODEL_PATH"].touch()
    model = Mock()
    monkeypatch.setattr(prediction["joblib"], "load", lambda _: model)
    loaded = prediction["load_saved_model"]()
    assert loaded[0] is model
    assert prediction["MODEL_SOURCE"] == "unknown"
    assert prediction["MODEL_CONFIDENCE"] is None


def test_inference_mode_does_not_load_tower_datasets(prediction, monkeypatch):
    model = Mock(n_features_in_=7)
    model.predict.return_value = np.array([0.7])
    monkeypatch.setitem(prediction, "load_saved_model", lambda: (model, "test"))
    towers = Mock(side_effect=AssertionError("Inference must not load training datasets"))
    monkeypatch.setitem(prediction, "load_available_tower_datasets", towers)
    assert prediction["train_or_load_model"]()[0] is model
    model.set_params.assert_called_once_with(n_jobs=prediction["MODEL_THREADS"])
    towers.assert_not_called()


@pytest.mark.parametrize("features", [0, 6, 8])
def test_wrong_model_features_are_rejected(prediction, monkeypatch, features):
    monkeypatch.setitem(prediction, "load_saved_model", lambda: (Mock(n_features_in_=features), "test"))
    with pytest.raises(RuntimeError, match="feature count"):
        prediction["train_or_load_model"]()


@pytest.mark.parametrize("field,value", [("lat", 91), ("lon", -181), ("length", -1), ("id", "")])
def test_invalid_inputs_are_422(prediction, field, value):
    import asyncio
    segment = {"id": "a", "lat": 12.97, "lon": 77.59, "length": 100, field: value}
    assert asyncio.run(post(prediction, [segment])).status_code == 422


def test_duplicate_ids_are_422_and_unavailable_model_is_503(prediction, monkeypatch):
    import asyncio
    segment = {"id": "a", "lat": 12.97, "lon": 77.59}
    assert asyncio.run(post(prediction, [segment])).status_code == 503
    monkeypatch.setitem(prediction, "MODEL", object())
    assert asyncio.run(post(prediction, [segment, segment])).status_code == 422


@pytest.mark.parametrize("output", [np.array([np.nan]), np.array([]), np.array([0.2, 0.3])])
def test_malformed_inference_is_explicit_503(prediction, monkeypatch, output):
    import asyncio
    monkeypatch.setitem(prediction, "MODEL", object())
    monkeypatch.setitem(prediction, "predict_batch_gpu", lambda _: output)
    response = asyncio.run(post(prediction, [{"id": "a", "lat": 12.97, "lon": 77.59}]))
    assert response.status_code == 503
    assert "Traceback" not in response.text


def test_concurrent_inference_is_serialized_and_preserves_revisions(prediction, monkeypatch):
    import asyncio
    active = 0
    peak = 0
    lock = threading.Lock()
    def infer(features):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        result = np.array([0.625] * len(features))
        with lock:
            active -= 1
        return result
    monkeypatch.setitem(prediction, "MODEL", object())
    monkeypatch.setitem(prediction, "predict_batch_gpu", infer)
    async def requests():
        return await asyncio.gather(*(post(prediction, [{"id": str(i), "lat": 12.97, "lon": 77.59}]) for i in range(8)))
    responses = asyncio.run(requests())
    assert peak == 1
    for i, response in enumerate(responses):
        assert response.status_code == 200
        assert response.json()["scores"] == {str(i): 0.625}
        assert response.json()["graph_revision"] == "graph-a"


def test_feature_clock_uses_india_and_explicit_hour(prediction, monkeypatch):
    from datetime import datetime
    from types import SimpleNamespace
    zones = []
    def now(zone):
        zones.append(str(zone))
        return datetime(2026, 10, 6, 21)
    monkeypatch.setitem(prediction, "datetime", SimpleNamespace(now=now))
    segment = prediction["SegmentPayload"](id="a", lat=12.97, lon=77.59)
    features = prediction["build_feature_matrix"]([segment], city="bangalore")
    assert zones == ["Asia/Kolkata"]
    assert features[0, 3:5].tolist() == [21, 1]
    assert prediction["build_feature_matrix"]([segment], city="bangalore", hour_of_day=14)[0, 3:5].tolist() == [14, 0]
