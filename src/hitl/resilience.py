"""Retry and circuit breaking for a Jira that is sometimes not there.

The hard constraint is the one `graph.py` already states: an approved action
executes once. None of Jira's mutations are idempotent -- a retried
`create_issue` is two issues, a retried `add_comment` is two comments -- so
wrapping `execute` in a blanket retry would turn a flaky network into
duplicated work that a human approved exactly once.

So retries are split by what the failure *proves*:

  * A read has no side effect. Retry it on anything that looks like
    infrastructure.
  * A mutation is retried only on failures that prove the request never
    reached Jira: a refused connection, a DNS failure, or a backend that
    explicitly said it did not process the request. A timeout or a reset
    connection is ambiguous -- the write may well have landed -- so it is
    never retried, and the caller is told the outcome is unknown.

The circuit breaker covers the other half: when Jira is down, stop asking.
It counts only availability failures. Jira answering "no transition to Done"
is Jira working perfectly, and tripping a breaker on it would take the whole
system down over one misconfigured workflow.
"""

from __future__ import annotations

import socket
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

from hitl.logging import log_event

T = TypeVar("T")


class TransientError(Exception):
    """Raised by a backend to say it was busy and applied nothing.

    A 429 or a 503 is this: the server is explicitly declining to process the
    request, which makes a retry safe even for a mutation.
    """


class CircuitOpen(Exception):
    """The breaker is open, so the call was never attempted."""


# Proof that the request never reached Jira: retrying cannot duplicate
# anything, even a mutation.
NEVER_APPLIED: tuple[type[BaseException], ...] = (
    ConnectionRefusedError,
    socket.gaierror,
    TransientError,
)

# Transport-level failure of any kind. Deliberately a SUPERSET of
# NEVER_APPLIED -- ConnectionRefusedError is also a ConnectionError, and
# socket.gaierror is also an OSError -- so the two tuples are not a partition
# and must never be used as one. `never_applied` is the narrow test and always
# takes precedence; `ambiguous` is what is left over.
TRANSPORT: tuple[type[BaseException], ...] = (
    ConnectionResetError,
    TimeoutError,
    ConnectionError,
    OSError,
)


def never_applied(exc: BaseException) -> bool:
    """True when the failure proves Jira did not process the request."""
    return isinstance(exc, NEVER_APPLIED)


def transient(exc: BaseException) -> bool:
    """True for infrastructure failures, as opposed to Jira's own answer."""
    return isinstance(exc, NEVER_APPLIED) or isinstance(exc, TRANSPORT)


def ambiguous(exc: BaseException) -> bool:
    """Transient, but it may already have been applied.

    This is the set a mutation must never retry: the request reached Jira, or
    might have, and repeating it could duplicate the write.
    """
    return transient(exc) and not never_applied(exc)


def retry(
    fn: Callable[[], T],
    *,
    attempts: int = 3,
    backoff: float = 0.5,
    retryable: Callable[[BaseException], bool] = never_applied,
    sleep: Callable[[float], None] = time.sleep,
    label: str = "call",
) -> T:
    """Call `fn`, retrying with exponential backoff while `retryable` allows.

    The default predicate is the conservative one. A caller that wants a read
    retried on anything transient has to ask for it explicitly, so that adding
    a new mutation cannot silently inherit a retry it must not have.
    """
    if attempts < 1:
        raise ValueError("attempts must be >= 1")

    for attempt in range(attempts - 1):
        try:
            return fn()
        except Exception as exc:
            if not retryable(exc):
                raise
            delay = backoff * (2**attempt)
            log_event(
                "retry_scheduled",
                label=label,
                attempt=attempt + 1,
                attempts=attempts,
                delay_seconds=delay,
                error=str(exc),
            )
            sleep(delay)
    # Last attempt: whatever it raises is the caller's answer.
    return fn()


@dataclass
class CircuitBreaker:
    """Stop calling a backend that is failing.

        closed    --`threshold` consecutive availability failures--> open
        open      --`recovery` seconds elapse-------------------> half_open
        half_open --one success--> closed / --one failure--> open

    Only failures accepted by `counts` move the needle, so Jira refusing an
    action never trips it.
    """

    threshold: int = 5
    recovery: float = 30.0
    counts: Callable[[BaseException], bool] = transient
    clock: Callable[[], float] = time.monotonic
    failures: int = 0
    opened_at: float | None = None

    @property
    def state(self) -> str:
        if self.opened_at is None:
            return "closed"
        if self.clock() - self.opened_at >= self.recovery:
            return "half_open"
        return "open"

    def call(self, fn: Callable[[], T]) -> T:
        if self.state == "open":
            raise CircuitOpen(
                f"circuit open after {self.failures} consecutive failures; "
                f"retrying in {self.recovery - (self.clock() - self.opened_at):.0f}s"
            )
        try:
            result = fn()
        except Exception as exc:
            if self.counts(exc):
                self._fail()
            else:
                # Jira answered. "No" is still an answer, and it proves the
                # backend is up, so a half-open circuit closes on it too.
                self._reset()
            raise
        self._reset()
        return result

    def _fail(self) -> None:
        if self.state == "half_open":
            # One strike while probing re-opens immediately; making it serve
            # another full `threshold` would hammer a backend still on its back.
            self.opened_at = self.clock()
            log_event("circuit_reopened", failures=self.failures)
            return
        self.failures += 1
        if self.failures >= self.threshold and self.opened_at is None:
            self.opened_at = self.clock()
            log_event(
                "circuit_opened",
                failures=self.failures,
                recovery_seconds=self.recovery,
            )

    def _reset(self) -> None:
        if self.opened_at is not None:
            log_event("circuit_closed", after_failures=self.failures)
        self.failures = 0
        self.opened_at = None
