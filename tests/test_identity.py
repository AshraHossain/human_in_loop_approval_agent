import pytest
from hitl.identity import (
    ApprovalLevel,
    Identity,
    IdentityProvider,
    InsufficientLevelError,
    MockIdentityProvider,
    UnknownIdentityError,
    require_level,
    verify_identity,
)


def test_the_base_provider_refuses_to_verify_anything():
    # Fail closed: a provider that forgot to implement verify must not be
    # mistaken for one that checked and found nobody.
    with pytest.raises(NotImplementedError):
        IdentityProvider().verify("alice")


def test_approval_level_hierarchy():
    assert ApprovalLevel.JUNIOR.value < ApprovalLevel.SENIOR.value
    assert ApprovalLevel.SENIOR.value < ApprovalLevel.LEAD.value


def test_identity_can_approve_at_level():
    identity = Identity(user_id="alice", level=ApprovalLevel.SENIOR)
    assert identity.can_approve(ApprovalLevel.JUNIOR)
    assert identity.can_approve(ApprovalLevel.SENIOR)
    assert not identity.can_approve(ApprovalLevel.LEAD)


def test_identity_can_approve_same_level():
    identity = Identity(user_id="bob", level=ApprovalLevel.LEAD)
    assert identity.can_approve(ApprovalLevel.LEAD)


def test_junior_cannot_approve_senior():
    identity = Identity(user_id="charlie", level=ApprovalLevel.JUNIOR)
    assert not identity.can_approve(ApprovalLevel.SENIOR)
    assert not identity.can_approve(ApprovalLevel.LEAD)


def test_mock_identity_provider_register():
    provider = MockIdentityProvider()
    provider.register("alice", ApprovalLevel.SENIOR, name="Alice Smith")

    identity = provider.verify("alice")
    assert identity is not None
    assert identity.user_id == "alice"
    assert identity.level == ApprovalLevel.SENIOR
    assert identity.name == "Alice Smith"


def test_mock_identity_provider_unknown_user():
    provider = MockIdentityProvider()
    identity = provider.verify("unknown")
    assert identity is None


def test_verify_identity_success():
    provider = MockIdentityProvider()
    provider.register("alice", ApprovalLevel.LEAD)

    identity = verify_identity(provider, "alice")
    assert identity.user_id == "alice"
    assert identity.level == ApprovalLevel.LEAD


def test_verify_identity_raises_on_unknown():
    provider = MockIdentityProvider()

    with pytest.raises(UnknownIdentityError, match="unknown user"):
        verify_identity(provider, "unknown")


def test_require_level_sufficient():
    identity = Identity(user_id="bob", level=ApprovalLevel.LEAD)
    require_level(identity, ApprovalLevel.SENIOR)
    # Should not raise


def test_require_level_exact():
    identity = Identity(user_id="charlie", level=ApprovalLevel.SENIOR)
    require_level(identity, ApprovalLevel.SENIOR)
    # Should not raise


def test_require_level_insufficient():
    identity = Identity(user_id="david", level=ApprovalLevel.JUNIOR)

    with pytest.raises(InsufficientLevelError, match="cannot approve at SENIOR"):
        require_level(identity, ApprovalLevel.SENIOR)


def test_require_level_junior_cannot_lead():
    identity = Identity(user_id="eve", level=ApprovalLevel.JUNIOR)

    with pytest.raises(InsufficientLevelError, match="JUNIOR"):
        require_level(identity, ApprovalLevel.LEAD)


def test_identity_multiple_registrations():
    provider = MockIdentityProvider()
    provider.register("alice", ApprovalLevel.JUNIOR)
    provider.register("bob", ApprovalLevel.SENIOR)
    provider.register("charlie", ApprovalLevel.LEAD)

    assert provider.verify("alice").level == ApprovalLevel.JUNIOR
    assert provider.verify("bob").level == ApprovalLevel.SENIOR
    assert provider.verify("charlie").level == ApprovalLevel.LEAD


def test_identity_with_contact_info():
    identity = Identity(
        user_id="frank",
        level=ApprovalLevel.SENIOR,
        name="Frank",
        email="frank@example.com",
    )

    assert identity.name == "Frank"
    assert identity.email == "frank@example.com"
    assert identity.can_approve(ApprovalLevel.JUNIOR)
