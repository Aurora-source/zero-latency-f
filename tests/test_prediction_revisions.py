from __future__ import annotations

import asyncio
import runpy
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock, patch

import httpx
import numpy as np
import pytest


PREDICTION_MAIN = (
    Path(__file__).resolve().parents[1] / "services" / "prediction-service" / "main.py"
)


@pytest.fixture(scope="module")
def prediction():
    # This contract test needs no ML runtimes. Guard imports as well as startup
    # so it cannot load models, data or GPU libraries, even when installed.
    with patch.dict(
        sys.modules,
        {
            "joblib": ModuleType("joblib"),
            "xgboost": ModuleType("xgboost"),
            "lightgbm": None,
            "torch": None,
            "cupy": None,
        },
    ):
        return runpy.run_path(str(PREDICTION_MAIN))


@pytest.mark.parametrize("revision", [None, "graph-a", "Graph/opaque:007"])
@pytest.mark.parametrize("empty", [False, True])
def test_predict_echoes_request_graph_without_changing_scores(prediction, revision, empty):
    payload = {"city": "bangalore", "segments": []}
    if not empty:
        payload["segments"] = [
            {"id": str(index), "lat": 12.97, "lon": 77.59, "length": 100.0}
            for index in range(3)
        ]
    if revision is not None:
        payload["graph_revision"] = revision

    predictor = Mock(return_value=np.asarray([-0.2, 0.6544, 1.2], dtype=np.float32))

    async def call_endpoint():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=prediction["app"]),
            base_url="http://test",
            trust_env=False,
        ) as client:
            return await client.post("/predict", json=payload)

    with patch.dict(
        prediction["predict_scores"].__globals__,
        {
            "predict_batch_gpu": predictor,
            "MODEL_SOURCE": "synthetic",
            "MODEL_CONFIDENCE": 0.65,
            "USE_GPU": False,
            "USE_CUPY": False,
        },
    ):
        response = asyncio.run(call_endpoint())

    assert response.status_code == 200
    result = response.json()
    assert result["graph_revision"] == revision
    assert result["data_source"] == "synthetic"
    assert result["confidence"] == 0.65
    if empty:
        assert result["scores"] == {}
        predictor.assert_not_called()
    else:
        assert result["scores"] == pytest.approx({"0": 0.0, "1": 0.654, "2": 1.0})
        predictor.assert_called_once()
