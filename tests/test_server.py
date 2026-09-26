"""The probe endpoint.

`serve()` installs signal handlers, which only the main thread may do, so
the routing is tested against `HealthServer` directly and the shutdown
behaviour in a subprocess where there is a real main thread to signal.
"""

import json
import os
import signal
import subprocess
import sys
import textwrap
import threading
import urllib.error
import urllib.request

import pytest

from hitl.config import Config
from hitl.server import HealthServer


@pytest.fixture
def serving(tmp_path):
    def start(jira=None, **config_kw):
        server = HealthServer(("127.0.0.1", 0), Config(home=tmp_path, **config_kw), jira)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        started.append((server, thread))
        return f"http://127.0.0.1:{server.server_address[1]}"

    started: list = []
    yield start
    for server, thread in started:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _get(url):
    try:
        with urllib.request.urlopen(url, timeout=5) as response:  # noqa: S310
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


# --- /health --------------------------------------------------------------


def test_health_answers_200_when_degraded(serving, tmp_path):
    """No approvers yet, which is degraded -- but restarting would not add
    any, so the probe must not report it as dead."""
    status, body = _get(serving() + "/health")
    assert status == 200
    assert body["status"] == "degraded"


def test_health_answers_200_when_fully_ok(serving, tmp_path):
    (tmp_path / "identities.json").write_text('{"ash": "lead"}')
    status, body = _get(serving() + "/health")
    assert status == 200
    assert body["status"] == "ok"


def test_health_answers_503_when_failing(serving, tmp_path):
    (tmp_path / "checkpoints.sqlite").write_bytes(b"not a database")
    status, body = _get(serving() + "/health")
    assert status == 503
    assert body["status"] == "failing"


def test_healthz_is_the_same_endpoint(serving):
    assert _get(serving() + "/healthz")[0] == 200


def test_health_lists_the_individual_checks(serving):
    _, body = _get(serving() + "/health")
    assert {c["name"] for c in body["checks"]} == {
        "checkpoints",
        "audit_dir",
        "identities",
        "jira",
    }


def test_the_shallow_probe_skips_the_chain(serving):
    """A liveness probe runs every few seconds; walking every audit record
    that often would be wasteful."""
    _, body = _get(serving() + "/health")
    assert "audit_chain" not in {c["name"] for c in body["checks"]}


def test_deep_adds_the_expensive_checks(serving):
    _, body = _get(serving() + "/health?deep=1")
    assert {"audit_chain", "pending_approvals"} <= {c["name"] for c in body["checks"]}


def test_a_deep_value_other_than_one_stays_shallow(serving):
    _, body = _get(serving() + "/health?deep=0")
    assert "audit_chain" not in {c["name"] for c in body["checks"]}


# --- /metrics -------------------------------------------------------------


def test_metrics_are_served(serving):
    status, body = _get(serving() + "/metrics")
    assert status == 200
    assert "approvals_total" in body


# --- everything else ------------------------------------------------------


def test_an_unknown_path_is_404(serving):
    status, body = _get(serving() + "/nope")
    assert status == 404
    assert "no such path" in body["error"]


def test_the_root_path_is_404(serving):
    assert _get(serving() + "/")[0] == 404


def test_the_server_handles_several_requests(serving):
    url = serving()
    assert [_get(url + "/health")[0] for _ in range(5)] == [200] * 5


# --- graceful shutdown ----------------------------------------------------

SERVE_SCRIPT = textwrap.dedent(
    """
    import sys, json
    sys.path.insert(0, %r)
    from hitl.config import Config
    from hitl.server import serve
    import hitl.server as server_module

    real = server_module.HealthServer
    class Announcing(real):
        def __init__(self, address, config, jira=None):
            super().__init__(address, config, jira)
            print("PORT=%%d" %% self.server_address[1], flush=True)
    server_module.HealthServer = Announcing

    rc = serve(Config(home=%r), port=0)
    print("EXIT=%%d" %% rc, flush=True)
    """
)


def _spawn_server(tmp_path):
    project = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    proc = subprocess.Popen(
        [
            sys.executable,
            "-c",
            SERVE_SCRIPT % (os.path.join(project, "src"), str(tmp_path)),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    port = None
    for _ in range(100):
        line = proc.stdout.readline()
        if line.startswith("PORT="):
            port = int(line.strip().split("=")[1])
            break
    assert port, "server never reported a port"
    return proc, port


@pytest.mark.parametrize("sig", [signal.SIGTERM, signal.SIGINT])
def test_the_server_shuts_down_cleanly_on_a_signal(tmp_path, sig):
    proc, port = _spawn_server(tmp_path)
    assert _get(f"http://127.0.0.1:{port}/health")[0] == 200

    proc.send_signal(sig)
    out, _ = proc.communicate(timeout=30)

    assert proc.returncode == 0, "a signalled shutdown is not a crash"
    assert "EXIT=0" in out


def test_the_port_is_released_after_shutdown(tmp_path):
    """A socket left in the listening state would stop the replacement
    process from binding."""
    proc, port = _spawn_server(tmp_path)
    proc.send_signal(signal.SIGTERM)
    proc.communicate(timeout=30)

    with pytest.raises(urllib.error.URLError):
        _get(f"http://127.0.0.1:{port}/health")
