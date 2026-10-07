from pathlib import Path
import os
import runpy
import socket
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

LAUNCHER = Path(__file__).resolve().parents[1] / "run-local.py"


@pytest.fixture
def launcher():
    return runpy.run_path(str(LAUNCHER))["main"].__globals__


def test_environment_is_explicit_cpu_local_only_and_credential_free(launcher, monkeypatch, tmp_path):
    monkeypatch.setenv("OPENCELLID_TOKEN", "must-not-be-inherited")
    monkeypatch.setenv("HTTP_PROXY", "must-not-be-inherited")
    environment = launcher["local_environment"](tmp_path, "/project/node/bin/node")
    assert "OPENCELLID_TOKEN" not in environment
    assert "HTTP_PROXY" not in environment
    assert environment["LOCAL_DATA_ONLY"] == "1"
    assert environment["ALLOW_MODEL_TRAINING"] == "0"
    assert environment["PREDICTION_DEVICE"] == "cpu"
    assert environment["ENV_FILE_PATH"] == launcher["os"].devnull


def test_copy_preserves_inputs_and_rejects_overwriting_different_work(launcher, tmp_path):
    source = tmp_path / "source"
    target = tmp_path / "working/copy"
    source.write_bytes(b"original")
    launcher["copy_input"](source, target)
    assert source.read_bytes() == target.read_bytes() == b"original"
    target.write_bytes(b"existing work")
    with pytest.raises(ValueError, match="already exists"):
        launcher["copy_input"](source, target)
    assert source.read_bytes() == b"original"
    assert target.read_bytes() == b"existing work"


def test_restart_preserves_migrated_graph_when_original_source_is_unchanged(launcher, tmp_path):
    source, target = tmp_path / "legacy", tmp_path / "working"
    source.write_bytes(b"legacy graph")
    launcher["copy_input"](source, target, mutable=True)
    target.write_bytes(b"graph with published revision")
    launcher["copy_input"](source, target, mutable=True)
    assert target.read_bytes() == b"graph with published revision"
    source.write_bytes(b"replacement input")
    with pytest.raises(ValueError):
        launcher["copy_input"](source, target, mutable=True)


def test_active_listener_is_still_rejected(launcher):
    with socket.socket() as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("127.0.0.1", 0))
        server.listen()
        assert not launcher["port_is_available"](server.getsockname()[1])


@pytest.mark.skipif(os.name != "posix", reason="POSIX TIME_WAIT restart behavior")
def test_closed_service_connections_do_not_prevent_restart(launcher):
    with socket.socket() as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("127.0.0.1", 0))
        port = server.getsockname()[1]
        server.listen()
        with socket.create_connection(("127.0.0.1", port)) as client:
            accepted, _ = server.accept()
            accepted.close()  # Server initiates close and retains TIME_WAIT.
            assert client.recv(1) == b""
    with socket.socket() as unreusable:
        with pytest.raises(OSError):
            unreusable.bind(("127.0.0.1", port))
    assert launcher["port_is_available"](port)


@pytest.mark.parametrize("attribute", ["command", "cwd", "created_at"])
def test_pid_reuse_or_different_owner_is_not_stopped(launcher, monkeypatch, attribute, tmp_path):
    process = SimpleNamespace(cmdline=lambda: ["python", "owned.py"], cwd=lambda: str(tmp_path), create_time=lambda: 10)
    monkeypatch.setattr(launcher["psutil"], "Process", lambda _: process)
    entry = {"pid": 123, "command": ["python", "owned.py"], "cwd": str(tmp_path), "created_at": 10}
    entry[attribute] = {"command": ["python", "unrelated.py"], "cwd": str(tmp_path / "other"), "created_at": 20}[attribute]
    kill = Mock(side_effect=AssertionError("Unrelated processes must survive"))
    monkeypatch.setattr(launcher["os"], "killpg", kill)
    launcher["stop_owned"]([entry])
    kill.assert_not_called()
