"""Ship audit records to an external SIEM (Splunk HEC, Datadog, any webhook).

Records go out as JSON lines in batches. Both Splunk and Datadog accept that
natively, so there is no CEF translation layer here.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from hitl.logging import log_event, record_error


class SiemError(Exception):
    """A batch could not be delivered after every retry."""


@dataclass
class ExportResult:
    batches_sent: int = 0
    records_sent: int = 0
    retries: int = 0
    failures: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failures


def _http_sender(url: str, token: str | None, timeout: float) -> Callable[[bytes], None]:
    # The URL is configuration, which is a trust boundary: without this check a
    # `file:` or `ftp:` URL would make urlopen read the local disk instead of
    # shipping anywhere.
    scheme = urllib.parse.urlparse(url).scheme.lower()
    if scheme not in ("http", "https"):
        raise SiemError(f"refusing non-HTTP SIEM URL scheme: {scheme or '(none)'!r}")

    def send(payload: bytes) -> None:
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = urllib.request.Request(  # noqa: S310  -- scheme checked above
            url, data=payload, headers=headers, method="POST"
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            if response.status >= 300:
                raise SiemError(f"SIEM returned HTTP {response.status}")

    return send


def _batched(records: list[dict], size: int) -> Iterable[list[dict]]:
    for start in range(0, len(records), size):
        yield records[start : start + size]


def export_records(
    records: Iterable[dict],
    url: str,
    *,
    token: str | None = None,
    batch_size: int = 100,
    max_retries: int = 3,
    timeout: float = 10.0,
    backoff: float = 0.5,
    sender: Callable[[bytes], None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> ExportResult:
    """POST records to `url` in batches, retrying each batch with backoff.

    A batch that never lands is recorded in `result.failures` rather than
    raised: losing the rest of the export because one batch failed would be
    worse than shipping what we can and reporting the gap.
    """
    if batch_size < 1:
        raise ValueError("batch_size must be >= 1")

    send = sender or _http_sender(url, token, timeout)
    result = ExportResult()
    pending = list(records)

    for batch in _batched(pending, batch_size):
        payload = "\n".join(json.dumps(r, default=str) for r in batch).encode("utf-8")
        for attempt in range(max_retries):
            try:
                send(payload)
                result.batches_sent += 1
                result.records_sent += len(batch)
                break
            except (SiemError, urllib.error.URLError, OSError) as exc:
                last = attempt == max_retries - 1
                if last:
                    message = f"batch of {len(batch)} failed after {max_retries}: {exc}"
                    result.failures.append(message)
                    record_error(f"siem_export_failed: {message}")
                else:
                    result.retries += 1
                    sleep(backoff * (2**attempt))

    log_event(
        "siem_export_completed",
        batches_sent=result.batches_sent,
        records_sent=result.records_sent,
        retries=result.retries,
        failures=len(result.failures),
    )
    return result
