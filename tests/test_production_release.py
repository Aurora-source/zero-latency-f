"""Release invariants using small inputs; no genuine model/data needed in CI."""
import hashlib
import json
from pathlib import Path

import pytest
import yaml

from runtime.entrypoint import ARTIFACTS, prepare_graph, validate_artifacts, validate_configuration

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def inputs(tmp_path):
    for name in ARTIFACTS:
        (tmp_path / name).write_bytes(name.encode())
    manifest = {"schema": 1, "sha256": {name: hashlib.sha256(name.encode()).hexdigest() for name in ARTIFACTS}}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    return tmp_path, manifest


def test_manifest_accepts_exact_input_hashes(inputs):
    directory, manifest = inputs
    assert validate_artifacts(directory) == manifest


@pytest.mark.parametrize("name", ARTIFACTS)
def test_changed_or_missing_artifact_rejected(inputs, name):
    directory, _ = inputs
    (directory / name).write_bytes(b"changed")
    with pytest.raises(ValueError, match="Missing or changed"):
        validate_artifacts(directory)
    (directory / name).unlink()
    with pytest.raises(ValueError, match="Missing or changed"):
        validate_artifacts(directory)


def test_legacy_manifest_rejected(inputs):
    directory, _ = inputs
    (directory / "manifest.json").write_text('{"schema": 0}')
    with pytest.raises(ValueError, match="schema 1"):
        validate_artifacts(directory)


def test_graph_publication_preserved_across_restart(inputs, tmp_path):
    directory, manifest = inputs
    runtime = tmp_path / "graph-volume"
    source = directory / ARTIFACTS[0]
    checksum = manifest["sha256"][ARTIFACTS[0]]
    prepare_graph(source, runtime, checksum)
    (runtime / ARTIFACTS[0]).write_bytes(b"published graph with revision")
    prepare_graph(source, runtime, checksum)
    assert (runtime / ARTIFACTS[0]).read_bytes() == b"published graph with revision"
    assert source.read_bytes() == ARTIFACTS[0].encode()
    with pytest.raises(ValueError, match="different/unknown"):
        prepare_graph(source, runtime, "other release")


def test_interrupted_seed_can_recover(inputs, tmp_path, monkeypatch):
    directory, manifest = inputs
    runtime = tmp_path / "graph-volume"
    import runtime.entrypoint as bootstrap
    replace = bootstrap.os.replace
    def interrupted(source, target):
        if Path(target).suffix == ".graphml":
            raise OSError("interrupted graph publication")
        replace(source, target)
    monkeypatch.setattr(bootstrap.os, "replace", interrupted)
    with pytest.raises(OSError):
        prepare_graph(directory / ARTIFACTS[0], runtime, manifest["sha256"][ARTIFACTS[0]])
    assert not (runtime / ARTIFACTS[0]).exists()
    monkeypatch.setattr(bootstrap.os, "replace", replace)
    prepare_graph(directory / ARTIFACTS[0], runtime, manifest["sha256"][ARTIFACTS[0]])
    assert (runtime / ARTIFACTS[0]).read_bytes() == ARTIFACTS[0].encode()


def production_environment():
    return {str(k): str(v) for k, v in yaml.safe_load((ROOT / "docker-compose.yml").read_text())["x-environment"].items()} | {"CORS_ORIGINS": ""}


def test_same_origin_requires_no_cors():
    assert validate_configuration(production_environment()) == []


@pytest.mark.parametrize("name,value", [("ALLOW_MODEL_TRAINING", "1"), ("LOCAL_DATA_ONLY", "0"), ("DATA_SERVICE_URL", "http://localhost:8001"), ("CORS_ORIGINS", "*"), ("CORS_ORIGINS", "https://*.example.com"), ("CORS_ORIGINS", "https://example.com/path")])
def test_unsafe_production_configuration_rejected(name, value):
    environment = production_environment() | {name: value}
    with pytest.raises(ValueError):
        validate_configuration(environment)


def test_explicit_origins_supported():
    assert validate_configuration(production_environment() | {"CORS_ORIGINS": "https://example.com,http://localhost:8080"}) == ["https://example.com", "http://localhost:8080"]


def test_topology_limits_ports_and_graph_writers():
    configuration = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    services = configuration["services"]
    assert set(services) == {"gateway", "data-service", "routing-engine", "prediction-service"}
    for name, service in services.items():
        assert service["read_only"] and service["cap_drop"] == ["ALL"]
        assert service["logging"]["options"]["max-file"] == "3"
        assert service["mem_limit"] and service["cpus"]
        if name != "gateway":
            assert "ports" not in service
            assert service["volumes"][0]["read_only"]
    assert services["gateway"]["ports"][0].startswith("127.0.0.1:")
    assert "graph-publication:/runtime/graphs:ro" in services["routing-engine"]["volumes"]
    assert "graph-publication:/runtime/graphs" in services["data-service"]["volumes"]
    assert "depends_on" not in services["gateway"]
    assert "test-route/" not in (ROOT / "gateway/nginx.conf").read_text()
