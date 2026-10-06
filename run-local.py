"""Credential-free, CPU-only local mode for the existing developer launcher.

Copies supplied runtime inputs; never installs dependencies, downloads data, or
trains models. Compose remains authoritative for production. One process/service.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

import psutil

ROOT = Path(__file__).resolve().parent
SERVICES = (("prediction-service", 8003), ("data-service", 8001), ("routing-engine", 8002), ("visualization", 5173))


def copy_input(source: Path, target: Path, *, mutable: bool = False) -> None:
    source = source.resolve(strict=True)
    if source == target.resolve():
        return
    if target.exists():
        receipt = target.with_suffix(target.suffix + ".source-sha256")
        if mutable and receipt.exists() and receipt.read_text().strip() == hashlib.sha256(source.read_bytes()).hexdigest():
            return
        if hashlib.sha256(source.read_bytes()).digest() != hashlib.sha256(target.read_bytes()).digest():
            raise ValueError(f"Working input already exists and differs: {target}. Use a new runtime directory.")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    if mutable:
        target.with_suffix(target.suffix + ".source-sha256").write_text(hashlib.sha256(source.read_bytes()).hexdigest())


def local_environment(runtime: Path, node: str) -> dict[str, str]:
    # Do not inherit dotenv values, proxy credentials, or user configuration.
    environment = {
        "PATH": os.pathsep.join([str(Path(sys.executable).parent), str(Path(node).parent), os.defpath]),
        "LANG": "C.UTF-8", "PYTHONUNBUFFERED": "1", "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1", "LOCAL_DATA_ONLY": "1", "ENV_FILE_PATH": os.devnull,
        "SUPPORTED_CITIES": "bangalore", "DEFAULT_CITY": "bangalore",
        "PREDICTION_DEVICE": "cpu", "ALLOW_MODEL_TRAINING": "0", "MODEL_THREADS": "2",
        "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "2", "CUDA_VISIBLE_DEVICES": "",
        "APP_CACHE_DIR": str(runtime), "GRAPH_CACHE_DIR": str(runtime / "graphs"),
        "OSMNX_HTTP_CACHE_DIR": str(runtime / "osmnx-http"),
        "TOWER_CACHE_DB_PATH": str(runtime / "towers/tower_cache.db"),
        "LOCAL_TOWER_CSV_PATH": str(runtime / "towers/bangalore_towers.csv"),
        "LOCAL_TOWER_PROVENANCE": "unknown", "TOWER_DIR": str(runtime / "towers"),
        "REAL_SCORE_DIR": str(runtime / "scores"), "MODEL_DIR": str(runtime / "models"),
        "HOTSPOT_CACHE_PATH": str(runtime / "hotspots.json"),
        "ROUTE_CACHE_PATH": str(runtime / "route_cache.json"),
        "PREDICTION_SERVICE_URL": "http://127.0.0.1:8003", "DATA_SERVICE_URL": "http://127.0.0.1:8001",
        "TMPDIR": str(runtime / "tmp"), "XDG_CACHE_HOME": str(runtime),
    }
    if os.name == "nt":
        # Required by the Windows loader, contains no application credentials.
        environment["SystemRoot"] = os.environ.get("SystemRoot", r"C:\Windows")
    return environment


def process_matches(entry: dict) -> bool:
    try:
        process = psutil.Process(entry["pid"])
        return (process.cmdline() == entry["command"] and
                Path(process.cwd()).resolve() == Path(entry["cwd"]).resolve() and
                abs(process.create_time() - entry["created_at"]) < 1)
    except (psutil.Error, OSError):
        return False


def stop_owned(entries: list[dict]) -> None:
    for entry in reversed(entries):
        if not process_matches(entry):
            continue
        process = psutil.Process(entry["pid"])
        children = process.children(recursive=True)
        if os.name == "posix":
            if os.getpgid(process.pid) != process.pid:
                continue
            os.killpg(process.pid, signal.SIGTERM)
        else:
            for child in reversed(children):
                child.terminate()
            process.terminate()
        _, alive = psutil.wait_procs([process, *children], timeout=10)
        for survivor in alive:
            try:
                survivor.kill()  # psutil checks PID reuse; these are verified owned processes.
            except psutil.Error:
                pass
        psutil.wait_procs(alive, timeout=3)
        print(f"Stopped owned {entry['service']} PID {entry['pid']}", flush=True)


def wait_ready(process: subprocess.Popen, port: int, endpoint: str, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Service on {port} exited ({process.returncode}); inspect its runtime log")
        try:
            with opener.open(f"http://127.0.0.1:{port}{endpoint}", timeout=3) as response:
                if response.status == 200:
                    return
        except (OSError, urllib.error.URLError):
            pass
        time.sleep(1)
    raise RuntimeError(f"Service on {port} did not become ready in {timeout:g}s; inspect its runtime log")


def port_is_available(port: int) -> bool:
    with socket.socket() as sock:
        if os.name == "posix":
            # Match asyncio/Uvicorn: closed connections in TIME_WAIT do not mean
            # a service still owns the port. An active listener still blocks bind.
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-dir", type=Path, default=ROOT / ".cache/local-runtime")
    parser.add_argument("--graph", type=Path, help="Existing Bengaluru GraphML (copied)")
    parser.add_argument("--towers", type=Path, help="Existing local CSV (copied; unknown provenance)")
    parser.add_argument("--model", type=Path, help="Trusted seven-feature local model (copied)")
    parser.add_argument("--detach", action="store_true")
    parser.add_argument("--stop", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--ready-timeout", type=float, default=300)
    args = parser.parse_args()
    runtime = args.runtime_dir.resolve()
    if not runtime.is_relative_to(ROOT / ".cache"):
        parser.error("Runtime directory must be inside this checkout's ignored .cache directory")
    registry = runtime / "processes.json"
    if args.stop or args.status:
        entries = json.loads(registry.read_text()) if registry.exists() else []
        if args.stop:
            stop_owned(entries)
        else:
            for entry in entries:
                print(entry["service"], entry["pid"], "running" if process_matches(entry) else "stopped")
        return 0
    if not args.graph or not args.model:
        parser.error("--graph and --model are required; no download or training fallback")
    if sys.version_info[:2] != (3, 11) or sys.prefix == sys.base_prefix:
        parser.error("Run with the project-local Python 3.11 virtual environment")
    node = shutil.which("node")
    if not node or not subprocess.check_output([node, "--version"], text=True).startswith("v22."):
        parser.error("Node 22 must be on PATH")
    vite = ROOT / "services/visualization/node_modules/vite/bin/vite.js"
    if not vite.exists():
        parser.error("Install frontend dependencies with npm ci first")
    for _, port in SERVICES:
        if not port_is_available(port):
            parser.error(f"Port {port} is occupied; inspect its owner. No processes were stopped.")
    for folder in ("graphs", "towers", "models", "logs", "scores", "tmp"):
        (runtime / folder).mkdir(parents=True, exist_ok=True)
    copy_input(args.graph, runtime / "graphs/bangalore.graphml", mutable=True)
    copy_input(args.model, runtime / "models/connectivity_model.pkl")
    if args.towers:
        copy_input(args.towers, runtime / "towers/bangalore_towers.csv")
    environment = local_environment(runtime, node)
    entries, processes = [], []
    detached = False
    try:
        for service, port in SERVICES:
            cwd = ROOT / "services" / service
            command = ([node, str(vite), "--host", "127.0.0.1", "--port", str(port), "--strictPort"] if service == "visualization" else
                       [sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", str(port), "--workers", "1"])
            with (runtime / "logs" / f"{service}.log").open("ab") as log:
                process = subprocess.Popen(command, cwd=cwd, env=environment, stdout=log, stderr=log,
                                           start_new_session=os.name == "posix")
            processes.append(process)
            entries.append({"service": service, "pid": process.pid, "command": command, "cwd": str(cwd),
                            "created_at": psutil.Process(process.pid).create_time(), "port": port})
            registry.write_text(json.dumps(entries, indent=2))
            print(f"Starting {service} on localhost:{port}", flush=True)
            wait_ready(process, port, "/" if service == "visualization" else "/ready", args.ready_timeout)
            print(f"Ready: {service}", flush=True)
        print("Open http://127.0.0.1:5173 — local records and model estimates are not measured RF coverage.", flush=True)
        if args.detach:
            detached = True
            return 0
        while all(process.poll() is None for process in processes):
            time.sleep(1)
        raise RuntimeError("A local service exited; inspect runtime logs")
    except KeyboardInterrupt:
        return 0
    except (OSError, RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        if not detached:
            stop_owned(entries)


if __name__ == "__main__":
    raise SystemExit(main())
