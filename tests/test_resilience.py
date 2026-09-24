"""Retry and circuit breaking.

The invariant worth more than any of the others here: a Jira *mutation* that
fails ambiguously is attempted exactly once. Retrying it could create two
issues or post two comments from a single human approval, which is a worse
outcome than the failure it was trying to paper over.
"""

import socket

import pytest
from hitl.resilience import (
    NEVER_APPLIED,
    CircuitBreaker,
    CircuitOpen,
    TransientError,
    ambiguous,
    never_applied,
    retry,
    transient,
)


class Clock:
    """A hand-wound monotonic clock."""

    def __init__(self, now=0.0):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class Flaky:
    """Raises `raises` for the first `fail_times` calls, then returns `returns`."""

    def __init__(self, fail_times=0, raises=None, returns="ok"):
        self.calls = 0
        self._fail_times = fail_times
        self._raises = raises or ConnectionRefusedError("refused")
        self._returns = returns

    def __call__(self):
        self.calls += 1
        if self.calls <= self._fail_times:
            raise self._raises
        return self._returns


def _sleeps():
    recorded = []
    return recorded, recorded.append


# --- classification -------------------------------------------------------


@pytest.mark.parametrize(
    "exc",
    [ConnectionRefusedError("refused"), socket.gaierror("no dns"), TransientError("429")],
)
def test_these_failures_prove_nothing_was_applied(exc):
    assert never_applied(exc) is True
    assert transient(exc) is True
    assert ambiguous(exc) is False


@pytest.mark.parametrize(
    "exc",
    [
        ConnectionResetError("reset"),
        TimeoutError("timed out"),
        OSError("broken pipe"),
    ],
)
def test_these_failures_are_ambiguous_so_only_reads_may_retry(exc):
    """The write may have landed. Transient enough to retry a read, never
    enough to retry a mutation."""
    assert transient(exc) is True
    assert ambiguous(exc) is True
    assert never_applied(exc) is False


@pytest.mark.parametrize("exc", [ValueError("nope"), RuntimeError("boom")])
def test_application_errors_are_not_infrastructure(exc):
    assert transient(exc) is False
    assert never_applied(exc) is False
    assert ambiguous(exc) is False


def test_never_applied_wins_over_the_broader_transport_set():
    """NEVER_APPLIED members are subclasses of TRANSPORT members --
    ConnectionRefusedError IS a ConnectionError. The two are a superset
    relation, not a partition, so classification must not depend on which
    tuple is consulted first."""
    for kind in NEVER_APPLIED:
        exc = kind("x")
        assert never_applied(exc) is True, f"{kind} misclassified"
        assert ambiguous(exc) is False, f"{kind} must never be retried as a read-only"


# --- retry ----------------------------------------------------------------


def test_a_call_that_works_is_made_once():
    fn = Flaky(fail_times=0)
    assert retry(fn, sleep=lambda _: None) == "ok"
    assert fn.calls == 1


def test_a_retryable_failure_is_retried_until_it_works():
    fn = Flaky(fail_times=2)
    assert retry(fn, attempts=3, sleep=lambda _: None) == "ok"
    assert fn.calls == 3


def test_retry_gives_up_and_reraises_the_last_error():
    fn = Flaky(fail_times=99)
    with pytest.raises(ConnectionRefusedError):
        retry(fn, attempts=3, sleep=lambda _: None)
    assert fn.calls == 3, "exactly `attempts` calls, no more"


def test_a_non_retryable_failure_is_not_retried():
    fn = Flaky(fail_times=99, raises=ValueError("bad request"))
    with pytest.raises(ValueError):
        retry(fn, attempts=5, sleep=lambda _: None)
    assert fn.calls == 1, "a rejection is an answer, not a blip"


def test_the_backoff_is_exponential():
    recorded, sleep = _sleeps()
    with pytest.raises(ConnectionRefusedError):
        retry(Flaky(fail_times=99), attempts=4, backoff=0.5, sleep=sleep)
    assert recorded == [0.5, 1.0, 2.0]


def test_one_attempt_means_no_retry_and_no_sleep():
    recorded, sleep = _sleeps()
    fn = Flaky(fail_times=99)
    with pytest.raises(ConnectionRefusedError):
        retry(fn, attempts=1, sleep=sleep)
    assert fn.calls == 1
    assert recorded == []


def test_no_sleep_after_the_final_failure():
    """Sleeping before giving up just delays the bad news."""
    recorded, sleep = _sleeps()
    with pytest.raises(ConnectionRefusedError):
        retry(Flaky(fail_times=99), attempts=3, sleep=sleep)
    assert len(recorded) == 2, "two gaps between three attempts"


def test_zero_attempts_is_a_programming_error():
    with pytest.raises(ValueError, match="attempts must be >= 1"):
        retry(Flaky(), attempts=0)


def test_the_retryable_predicate_is_honoured():
    fn = Flaky(fail_times=1, raises=TimeoutError("slow"))
    # Default predicate refuses a timeout...
    with pytest.raises(TimeoutError):
        retry(fn, attempts=3, sleep=lambda _: None)
    assert fn.calls == 1

    # ...but a caller that knows the call is safe may widen it.
    fn = Flaky(fail_times=1, raises=TimeoutError("slow"))
    assert retry(fn, attempts=3, retryable=transient, sleep=lambda _: None) == "ok"
    assert fn.calls == 2


def test_retry_defaults_to_the_conservative_predicate():
    """A new mutation must not silently inherit a retry it must not have."""
    fn = Flaky(fail_times=1, raises=ConnectionResetError("reset"))
    with pytest.raises(ConnectionResetError):
        retry(fn, attempts=3, sleep=lambda _: None)
    assert fn.calls == 1


# --- circuit breaker ------------------------------------------------------


def _breaker(threshold=3, recovery=30.0, clock=None):
    return CircuitBreaker(threshold=threshold, recovery=recovery, clock=clock or Clock())


def _trip(breaker, times):
    for _ in range(times):
        with pytest.raises(ConnectionRefusedError):
            breaker.call(Flaky(fail_times=99))


def test_a_new_breaker_is_closed():
    assert _breaker().state == "closed"


def test_a_closed_breaker_passes_calls_through():
    assert _breaker().call(lambda: "ok") == "ok"


def test_failures_below_the_threshold_leave_it_closed():
    b = _breaker(threshold=3)
    _trip(b, 2)
    assert b.state == "closed"
    assert b.failures == 2


def test_it_opens_at_the_threshold():
    b = _breaker(threshold=3)
    _trip(b, 3)
    assert b.state == "open"


def test_an_open_breaker_fails_fast_without_calling():
    b = _breaker(threshold=1)
    _trip(b, 1)

    fn = Flaky(fail_times=0)
    with pytest.raises(CircuitOpen, match="circuit open"):
        b.call(fn)
    assert fn.calls == 0, "the whole point is not to call a backend that is down"


def test_a_success_resets_the_failure_count():
    b = _breaker(threshold=3)
    _trip(b, 2)
    b.call(lambda: "ok")
    assert b.failures == 0
    assert b.state == "closed"


def test_it_goes_half_open_once_recovery_elapses():
    clock = Clock()
    b = _breaker(threshold=1, recovery=30.0, clock=clock)
    _trip(b, 1)
    assert b.state == "open"

    clock.advance(29.9)
    assert b.state == "open"
    clock.advance(0.1)
    assert b.state == "half_open"


def test_a_half_open_breaker_lets_one_call_through_and_closes_on_success():
    clock = Clock()
    b = _breaker(threshold=1, recovery=10.0, clock=clock)
    _trip(b, 1)
    clock.advance(10.0)

    assert b.call(lambda: "ok") == "ok"
    assert b.state == "closed"
    assert b.failures == 0


def test_one_failure_while_half_open_reopens_immediately():
    """Probing a backend that is still down must not cost another full
    threshold of calls."""
    clock = Clock()
    b = _breaker(threshold=3, recovery=10.0, clock=clock)
    _trip(b, 3)
    clock.advance(10.0)
    assert b.state == "half_open"

    _trip(b, 1)
    assert b.state == "open"


def test_the_recovery_window_restarts_when_it_reopens():
    clock = Clock()
    b = _breaker(threshold=1, recovery=10.0, clock=clock)
    _trip(b, 1)
    clock.advance(10.0)
    _trip(b, 1)  # reopens at t=10

    clock.advance(9.9)
    assert b.state == "open"
    clock.advance(0.1)
    assert b.state == "half_open"


def test_the_backend_saying_no_does_not_trip_the_breaker():
    """Jira refusing an action is Jira working. Tripping on it would take the
    system down over one misconfigured workflow."""
    b = _breaker(threshold=2)
    for _ in range(5):
        with pytest.raises(ValueError):
            b.call(Flaky(fail_times=99, raises=ValueError("no such transition")))
    assert b.state == "closed"
    assert b.failures == 0


def test_an_answered_call_resets_the_failure_count_even_when_it_errors():
    b = _breaker(threshold=3)
    _trip(b, 2)
    with pytest.raises(ValueError):
        b.call(Flaky(fail_times=99, raises=ValueError("rejected")))
    assert b.failures == 0, "the backend answered, so it is evidently up"


def test_a_half_open_breaker_closes_on_a_rejection_too():
    clock = Clock()
    b = _breaker(threshold=1, recovery=10.0, clock=clock)
    _trip(b, 1)
    clock.advance(10.0)

    with pytest.raises(ValueError):
        b.call(Flaky(fail_times=99, raises=ValueError("rejected")))
    assert b.state == "closed"


def test_the_open_message_says_how_long_is_left():
    clock = Clock()
    b = _breaker(threshold=1, recovery=30.0, clock=clock)
    _trip(b, 1)
    clock.advance(10.0)

    with pytest.raises(CircuitOpen, match="retrying in 20s"):
        b.call(lambda: "ok")


def test_the_exception_from_the_wrapped_call_is_not_swallowed():
    b = _breaker(threshold=5)
    with pytest.raises(ConnectionRefusedError, match="refused"):
        b.call(Flaky(fail_times=99))
