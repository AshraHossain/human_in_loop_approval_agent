"""Identity verification and RBAC."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class ApprovalLevel(Enum):
    """Approver authorization levels."""
    JUNIOR = 1
    SENIOR = 2
    LEAD = 3


_LEVEL_FOR_TIER = {
    "low": ApprovalLevel.JUNIOR,
    "medium": ApprovalLevel.SENIOR,
    "high": ApprovalLevel.LEAD,
}


def level_for_tier(tier: str) -> ApprovalLevel:
    """Level required to approve an action of this risk tier.

    Unknown tiers demand LEAD, mirroring `risk_tier`'s fail-closed default.
    """
    return _LEVEL_FOR_TIER.get(tier, ApprovalLevel.LEAD)


@dataclass
class Identity:
    """Verified identity with level."""
    user_id: str
    level: ApprovalLevel
    name: str | None = None
    email: str | None = None

    def can_approve(self, required_level: ApprovalLevel) -> bool:
        """Check if this identity can approve at the required level."""
        return self.level.value >= required_level.value


class IdentityProvider:
    """Trait for identity verification implementations."""

    def verify(self, user_id: str) -> Identity | None:
        """Verify identity and return authorized Identity or None."""
        raise NotImplementedError


class MockIdentityProvider(IdentityProvider):
    """In-memory identity provider for testing."""

    def __init__(self):
        self.users: dict[str, Identity] = {}

    def register(self, user_id: str, level: ApprovalLevel, name: str | None = None):
        """Register a test user."""
        self.users[user_id] = Identity(
            user_id=user_id,
            level=level,
            name=name,
        )

    def verify(self, user_id: str) -> Identity | None:
        """Look up user in registry."""
        return self.users.get(user_id)


class FileIdentityProvider(IdentityProvider):
    """Identities from a JSON file: `{"ash": "lead", "sam": "junior"}`.

    Read on every call rather than cached: revoking someone has to take effect
    on the next approval, not on the next restart. Anything the file does not
    say clearly -- missing file, unknown user, level that is not one of the
    three -- is not an identity, so verification fails closed.
    """

    def __init__(self, path: Path):
        self.path = path

    def verify(self, user_id: str) -> Identity | None:
        if not self.path.exists():
            return None
        users = json.loads(self.path.read_text(encoding="utf-8"))
        level = users.get(user_id)
        if not isinstance(level, str) or level.upper() not in ApprovalLevel.__members__:
            return None
        return Identity(user_id=user_id, level=ApprovalLevel[level.upper()])


class UnknownIdentityError(Exception):
    """Raised when identity cannot be verified."""


class InsufficientLevelError(Exception):
    """Raised when approver lacks required authorization level."""


def verify_identity(provider: IdentityProvider, user_id: str) -> Identity:
    """Verify identity or raise UnknownIdentityError."""
    identity = provider.verify(user_id)
    if not identity:
        raise UnknownIdentityError(f"unknown user: {user_id}")
    return identity


def require_level(identity: Identity, required_level: ApprovalLevel) -> None:
    """Verify identity can approve at this level or raise InsufficientLevelError."""
    if not identity.can_approve(required_level):
        raise InsufficientLevelError(
            f"user {identity.user_id} (level {identity.level.name}) "
            f"cannot approve at {required_level.name}"
        )
