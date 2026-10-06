"""Production bootstrap: trusted immutable inputs, isolated state, one worker.

Hashes detect accidental changes, not artifact authenticity or model quality.
Only deploy artifacts from a trusted source: the model is a Python pickle.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import os
from pathlib import Path
import shutil
import sys
from urllib.parse import urlsplit

ARTIFACTS = ("bangalore.graphml", "bangalore_towers.csv", "connectivity_model.pkl")
PORTS = {"data-service": 8001, "routing-engine": 8002, "prediction-service": 8003}


def digest(path: Path) -> str:
    checksum = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(block)
    return checksum.hexdigest()


def validate_artifacts(directory: Path) -> dict:
    manifest = json.loads((directory / "manifest.json").read_text())
    if manifest.get("schema") != 1 or set(manifest.get("sha256", {})) != set(ARTIFACTS):
        raise ValueError("Artifact manifest must declare the three supported inputs (schema 1)")
    for name in ARTIFACTS:
        path = directory / name
        if not path.is_file() or not path.stat().st_size or digest(path) != manifest["sha256"][name]:
            raise ValueError(f"Missing or changed artifact: {name}")
    return manifest


def validate_configuration(environment: dict[str, str]) -> list[str]:
    required = {"APP_ENV": "production", "LOCAL_DATA_ONLY": "1", "ALLOW_MODEL_TRAINING": "0",
                "PREDICTION_DEVICE": "cpu", "SUPPORTED_CITIES": "bangalore", "DEFAULT_CITY": "bangalore"}
    for name, expected in required.items():
        if environment.get(name) != expected:
            raise ValueError(f"Production requires {name}={expected}")
    for name, hostname, port in (("DATA_SERVICE_URL", "data-service", 8001),
                                 ("PREDICTION_SERVICE_URL", "prediction-service", 8003)):
        value = urlsplit(environment.get(name, ""))
        if (value.scheme, value.hostname, value.port) != ("http", hostname, port) or value.username or value.password or value.path or value.query or value.fragment:
            raise ValueError(f"{name} must use the internal service URL")
    origins = [item.strip() for item in environment.get("CORS_ORIGINS", "").split(",") if item.strip()]
    for origin in origins:
        parsed = urlsplit(origin)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or "*" in parsed.hostname or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
            raise ValueError("CORS_ORIGINS must contain explicit HTTP origins without paths")
    return origins


def prepare_graph(source: Path, directory: Path, source_hash: str) -> None:
    """Only data may seed the writable publication volume; never overwrite it.

    Its graph can legitimately acquire revision metadata after seeding. A receipt
    ties that mutable publication to its immutable source, not its current bytes.
    Changed release inputs require a new graph volume, preventing silent reuse.
    """
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / "bangalore.graphml"
    receipt = directory / "source-sha256"
    if target.exists():
        if not receipt.exists() or receipt.read_text().strip() != source_hash:
            raise ValueError("Graph volume belongs to different/unknown inputs; use a new release volume")
        return
    temporary = directory / ".bangalore.graphml.seed"
    shutil.copyfile(source, temporary)
    receipt_tmp = directory / ".source-sha256.seed"
    receipt_tmp.write_text(source_hash + "\n")
    # Publish receipt first: interruption before graph replacement is recoverable.
    os.replace(receipt_tmp, receipt)
    os.replace(temporary, target)


def main(service: str) -> None:
    if service not in PORTS:
        raise ValueError("Unknown production service")
    origins = validate_configuration(dict(os.environ))
    artifacts = Path("/artifacts")
    manifest = validate_artifacts(artifacts)
    if service == "data-service":
        prepare_graph(artifacts / "bangalore.graphml", Path(os.environ["GRAPH_CACHE_DIR"]), manifest["sha256"]["bangalore.graphml"])
    from fastapi.middleware.cors import CORSMiddleware
    sys.path.insert(0, str(Path.cwd()))
    module = importlib.import_module("main")
    # Same-origin gateway requests require no CORS. Never inherit dev wildcard.
    module.app.user_middleware = [item for item in module.app.user_middleware if item.cls is not CORSMiddleware]
    if origins:
        module.app.add_middleware(CORSMiddleware, allow_origins=origins,
                                  allow_credentials=False, allow_methods=["GET", "POST"], allow_headers=["Content-Type"])
    print(f"[release] {service}: validated immutable artifacts; CPU; one worker", flush=True)
    import uvicorn
    uvicorn.run(module.app, host="0.0.0.0", port=PORTS[service], workers=1,
                proxy_headers=False, timeout_graceful_shutdown=60)


if __name__ == "__main__":
    try:
        main(sys.argv[1])
    except (OSError, ValueError, KeyError) as exc:
        print(f"[release] startup rejected: {exc}", file=sys.stderr, flush=True)
        sys.exit(1)
