"""A probe endpoint, for when this runs as a service rather than a command.

    GET /health   200 ok/degraded, 503 failing
    GET /health?deep=1   also walks the audit chain and counts stuck requests
    GET /metrics  approval counts and latencies

`http.server` rather than a framework: three routes returning JSON is not
worth a dependency, and this listens on a probe port, not the internet.
"""

from __future__ import annotations

import json
import signal
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from hitl.health import check_health
from hitl.logging import get_metrics, log_event


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 -- BaseHTTPRequestHandler's spelling
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)

        if parsed.path in ("/health", "/healthz"):
            report = self.server.run_health(deep=query.get("deep", ["0"])[0] == "1")
            # 503 only for `failing`: see health.py on why a degraded service
            # must not be restarted out of its degradation.
            self._json(200 if report.ok else 503, report.to_dict())
        elif parsed.path == "/metrics":
            self._json(200, get_metrics())
        else:
            self._json(404, {"error": f"no such path: {parsed.path}"})

    def log_message(self, fmt: str, *args) -> None:
        # Default goes to stderr in Apache format, which would be the one
        # unstructured thing in an otherwise JSON log.
        log_event("http_request", level="debug", message=fmt % args)


class HealthServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, config, jira=None):
        super().__init__(address, _Handler)
        self._config = config
        self._jira = jira

    def run_health(self, *, deep: bool = False):
        return check_health(self._config, self._jira, deep=deep)


def serve(config, jira=None, *, host: str = "127.0.0.1", port: int = 8080) -> int:
    """Serve probes until SIGTERM or SIGINT, then stop accepting and drain.

    Binds to loopback by default. A health endpoint reports whether approvers
    exist and whether Jira is reachable, which is not information to hand to
    the network without someone deciding to.
    """
    server = HealthServer((host, port), config, jira)
    actual = server.server_address[1]
    log_event("server_started", host=host, port=actual)

    def stop(signum, _frame):
        log_event("server_stopping", signal=signum)
        # shutdown() blocks until the serve loop exits, so it cannot be
        # called from the loop's own thread.
        threading.Thread(target=server.shutdown, daemon=True).start()

    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, stop)

    try:
        server.serve_forever()
    finally:
        # Lets in-flight responses finish; daemon_threads means a wedged one
        # cannot hold the process open forever.
        server.server_close()
        log_event("server_stopped", port=actual)
    return 0
