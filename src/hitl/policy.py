"""Risk tiering, confidence, and the pause decision.

The invariant this module exists to enforce:

    Confidence may only ever ESCALATE to a gate.
    It can never clear one that policy requires.

That is the difference between HITL and HITL theater, and `decide()` is the
only place it is expressed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

TERMINAL_STATUSES = frozenset({"done", "closed", "resolved", "cancelled"})

# Ambiguity markers. Deliberately only a confidence signal -- never a
# substitute for the policy tier, which is derived from the action itself.
AMBIGUITY_MARKERS = (
    "maybe",
    "not sure",
    "unclear",
    "unknown",
    "ambiguous",
    "some kind of",
)

_TIER_BY_KIND = {
    "add_comment": "low",
    "create_issue": "medium",
}


@dataclass(frozen=True)
class Action:
    kind: str
    issue_key: str | None = None
    target_status: str | None = None
    body: str | None = None


@dataclass(frozen=True)
class Decision:
    gate: bool
    tier: str
    confidence: str
    reason: str
    checks: list[str] = field(default_factory=list)


def risk_tier(action: Action) -> str:
    """Tier derived from the ACTION, never from how the request was worded."""
    if action.kind == "transition":
        status = (action.target_status or "").strip().lower()
        return "high" if status in TERMINAL_STATUSES else "low"
    # Unknown kinds fail closed.
    return _TIER_BY_KIND.get(action.kind, "high")


def estimate_confidence(request: str) -> str:
    """Rule-based ambiguity estimate. Swap for structured LLM output later."""
    lowered = request.lower()
    hits = sum(marker in lowered for marker in AMBIGUITY_MARKERS)
    return "low" if hits else "high"


def decide(action: Action, request: str) -> Decision:
    """Combine tier and confidence into a gate decision.

    Escalate-only: `gate` is True if EITHER the tier requires it or confidence
    is low. There is deliberately no branch in which high confidence sets
    `gate` to False against a gating tier.
    """
    tier = risk_tier(action)
    confidence = estimate_confidence(request)

    tier_requires_gate = tier in ("medium", "high")
    confidence_requires_gate = confidence == "low"
    gate = tier_requires_gate or confidence_requires_gate

    if tier_requires_gate and confidence_requires_gate:
        reason = f"tier {tier} requires approval; request is also ambiguous"
    elif tier_requires_gate:
        reason = f"tier {tier} requires approval"
    elif confidence_requires_gate:
        reason = "request is ambiguous; escalating a low-tier action"
    else:
        reason = "low tier and unambiguous; proceeding automatically"

    return Decision(
        gate=gate,
        tier=tier,
        confidence=confidence,
        reason=reason,
        checks=[
            f"tier:{tier}",
            f"confidence:{confidence}",
            f"gate:{'required' if gate else 'not-required'}",
        ],
    )
