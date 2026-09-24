"""SIEM export: batching, retry, and honest reporting of what did not land."""

import json
import urllib.error
from unittest.mock import patch

import pytest
from hitl.siem import SiemError, _http_sender, export_records


class Recorder:
    """A sender that records payloads and can be told to fail."""

    def __init__(self, fail_times=0, fail_always=False):
        self.payloads: list[bytes] = []
        self.calls = 0
        self._fail_times = fail_times
        self._fail_always = fail_always

    def __call__(self, payload: bytes) -> None:
        self.calls += 1
        if self._fail_always or self.calls <= self._fail_times:
            raise SiemError("boom")
        self.payloads.append(payload)

    def records(self) -> list[dict]:
        out = []
        for payload in self.payloads:
            out += [json.loads(ln) for ln in payload.decode().splitlines()]
        return out


def _records(n: int) -> list[dict]:
    return [{"request_id": f"req-{i}", "stage": "completed"} for i in range(n)]


# --- batching -------------------------------------------------------------


def test_all_records_are_sent():
    sender = Recorder()
    result = export_records(_records(5), "http://siem", sender=sender)

    assert result.ok
    assert result.records_sent == 5
    assert [r["request_id"] for r in sender.records()] == [
        "req-0", "req-1", "req-2", "req-3", "req-4"
    ]


def test_records_are_split_into_batches():
    sender = Recorder()
    result = export_records(_records(10), "http://siem", batch_size=4, sender=sender)

    assert result.batches_sent == 3  # 4 + 4 + 2
    assert result.records_sent == 10
    sizes = [len(p.decode().splitlines()) for p in sender.payloads]
    assert sizes == [4, 4, 2]


def test_a_single_batch_when_it_fits():
    sender = Recorder()
    export_records(_records(3), "http://siem", batch_size=100, sender=sender)
    assert len(sender.payloads) == 1


def test_payload_is_json_lines():
    sender = Recorder()
    export_records(_records(2), "http://siem", sender=sender)

    lines = sender.payloads[0].decode().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["request_id"] == "req-0"


def test_empty_export_sends_nothing():
    sender = Recorder()
    result = export_records([], "http://siem", sender=sender)

    assert result.ok
    assert result.batches_sent == 0
    assert result.records_sent == 0
    assert sender.calls == 0


def test_batch_size_must_be_positive():
    with pytest.raises(ValueError, match="batch_size"):
        export_records(_records(1), "http://siem", batch_size=0, sender=Recorder())


def test_non_serializable_values_do_not_crash_the_export():
    from datetime import UTC, datetime

    sender = Recorder()
    result = export_records(
        [{"request_id": "req-1", "at": datetime.now(UTC)}],
        "http://siem",
        sender=sender,
    )
    assert result.ok


# --- retry ----------------------------------------------------------------


def test_transient_failure_is_retried_then_succeeds():
    sender = Recorder(fail_times=2)
    result = export_records(
        _records(1), "http://siem", sender=sender, sleep=lambda _: None
    )

    assert result.ok
    assert result.retries == 2
    assert result.records_sent == 1
    assert sender.calls == 3


def test_gives_up_after_max_retries():
    sender = Recorder(fail_always=True)
    result = export_records(
        _records(1),
        "http://siem",
        max_retries=3,
        sender=sender,
        sleep=lambda _: None,
    )

    assert not result.ok
    assert sender.calls == 3
    assert result.records_sent == 0
    assert "after 3" in result.failures[0]


def test_backoff_grows_exponentially():
    delays: list[float] = []
    sender = Recorder(fail_times=2)
    export_records(
        _records(1),
        "http://siem",
        backoff=0.5,
        sender=sender,
        sleep=delays.append,
    )
    assert delays == [0.5, 1.0]


def test_no_sleep_on_the_final_attempt():
    delays: list[float] = []
    export_records(
        _records(1),
        "http://siem",
        max_retries=2,
        sender=Recorder(fail_always=True),
        sleep=delays.append,
    )
    # 2 attempts -> only one gap between them.
    assert len(delays) == 1


def test_network_errors_are_retried_like_siem_errors():
    calls = {"n": 0}

    def flaky(payload):
        calls["n"] += 1
        if calls["n"] == 1:
            raise urllib.error.URLError("connection refused")

    result = export_records(
        _records(1), "http://siem", sender=flaky, sleep=lambda _: None
    )
    assert result.ok
    assert result.retries == 1


def test_one_bad_batch_does_not_lose_the_rest():
    # Losing the whole export because a single batch failed would be worse
    # than shipping what we can and reporting the gap.
    seen: list[bytes] = []

    def second_batch_always_fails(payload: bytes) -> None:
        if b"req-2" in payload:
            raise SiemError("boom")
        seen.append(payload)

    result = export_records(
        _records(6),
        "http://siem",
        batch_size=2,
        max_retries=2,
        sender=second_batch_always_fails,
        sleep=lambda _: None,
    )

    assert not result.ok
    assert len(result.failures) == 1
    assert result.batches_sent == 2  # first and third still landed
    assert result.records_sent == 4


def test_failure_is_recorded_as_an_error_metric():
    with patch("hitl.siem.record_error") as record:
        export_records(
            _records(1),
            "http://siem",
            max_retries=1,
            sender=Recorder(fail_always=True),
            sleep=lambda _: None,
        )
    assert record.called


# --- the HTTP sender ------------------------------------------------------


def _fake_urlopen(status=200):
    class _Response:
        def __init__(self):
            self.status = status

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    return _Response


def test_http_sender_posts_json():
    captured = {}

    def fake_urlopen(request, timeout=None):
        captured["request"] = request
        captured["timeout"] = timeout
        return _fake_urlopen()()

    with patch("urllib.request.urlopen", fake_urlopen):
        _http_sender("http://siem/hec", None, 7.5)(b'{"a":1}')

    request = captured["request"]
    assert request.method == "POST"
    assert request.full_url == "http://siem/hec"
    assert request.data == b'{"a":1}'
    assert request.headers["Content-type"] == "application/json"
    assert captured["timeout"] == 7.5


def test_http_sender_sends_bearer_token_when_given():
    captured = {}

    def fake_urlopen(request, timeout=None):
        captured["request"] = request
        return _fake_urlopen()()

    with patch("urllib.request.urlopen", fake_urlopen):
        _http_sender("http://siem", "s3cret", 10.0)(b"{}")

    assert captured["request"].headers["Authorization"] == "Bearer s3cret"


def test_http_sender_omits_auth_header_without_a_token():
    captured = {}

    def fake_urlopen(request, timeout=None):
        captured["request"] = request
        return _fake_urlopen()()

    with patch("urllib.request.urlopen", fake_urlopen):
        _http_sender("http://siem", None, 10.0)(b"{}")

    assert "Authorization" not in captured["request"].headers


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://host/path",
        "gopher://host",
        "/just/a/path",
        "",
    ],
)
def test_http_sender_refuses_non_http_urls(url):
    """The SIEM URL is config, and config is a trust boundary: a `file:` URL
    would make urlopen read local disk instead of shipping anywhere."""
    with pytest.raises(SiemError, match="refusing non-HTTP"):
        _http_sender(url, None, 10.0)


@pytest.mark.parametrize("url", ["http://siem", "https://siem", "HTTPS://SIEM"])
def test_http_sender_accepts_http_urls(url):
    assert _http_sender(url, None, 10.0) is not None


def test_export_refuses_a_file_url_before_sending_anything():
    with pytest.raises(SiemError, match="refusing non-HTTP"):
        export_records(_records(3), "file:///etc/passwd")


def test_http_sender_treats_error_status_as_failure():
    def fake_urlopen(request, timeout=None):
        return _fake_urlopen(status=503)()

    with patch("urllib.request.urlopen", fake_urlopen), pytest.raises(SiemError, match="503"):
        _http_sender("http://siem", None, 10.0)(b"{}")
