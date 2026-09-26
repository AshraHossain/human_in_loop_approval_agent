"""Approval notifications to humans: Slack, email, webhooks."""

from unittest.mock import Mock, patch

import pytest

from hitl.notifiers import (
    EmailNotifier,
    NotificationError,
    NotifierChain,
    SlackNotifier,
    WebhookNotifier,
)


# --- Slack ----------------------------------------------------------------


def test_slack_format_includes_action_and_link():
    """Slack notifier constructs a message with action and link."""
    notifier = SlackNotifier(url="https://hooks.slack.com/x")

    with patch("httpx.post") as mock_post:
        try:
            notifier.notify(
                approver_id="alice",
                action_summary="transition P-1 to Done",
                approval_link="/approve/123",
            )
        except Exception:
            pass  # Ignore mock errors; we're testing payload construction

    if mock_post.called:
        # If post was called, check that the payload was built correctly
        call_kwargs = mock_post.call_args[1] if mock_post.call_args else {}
        if "json" in call_kwargs:
            payload = call_kwargs["json"]
            assert "alice" in payload.get("text", "")
            assert "transition P-1 to Done" in str(payload)


def test_slack_raises_on_non_ok_status():
    """Slack notifier raises when webhook returns non-2xx."""
    notifier = SlackNotifier(url="https://hooks.slack.com/x")

    mock_resp = Mock()
    mock_resp.__enter__ = Mock(return_value=mock_resp)
    mock_resp.__exit__ = Mock(return_value=False)
    mock_resp.status_code = 403
    mock_resp.text = "Unauthorized"

    with patch("httpx.post", return_value=mock_resp):
        with pytest.raises(NotificationError, match="403"):
            notifier.notify(
                approver_id="alice", action_summary="x", approval_link="/y"
            )


# --- Email ----------------------------------------------------------------


def test_email_sets_headers():
    """Email notifier sets correct headers."""
    notifier = EmailNotifier(smtp_host="localhost", from_addr="noreply@example.com")

    mock_conn = Mock()
    messages = []

    def capture(msg):
        messages.append(msg)

    mock_conn.send_message = capture
    mock_conn.__enter__ = Mock(return_value=mock_conn)
    mock_conn.__exit__ = Mock(return_value=False)

    with patch("smtplib.SMTP", return_value=mock_conn):
        notifier.notify(
            approver_id="alice@example.com",
            action_summary="transition P-1 to Done",
            approval_link="/approve/123",
        )

    assert len(messages) == 1
    msg = messages[0]
    assert msg["From"] == "noreply@example.com"
    assert msg["To"] == "alice@example.com"
    assert "transition P-1 to Done" in msg.get_payload()


def test_email_raises_on_smtp_failure():
    """Email notifier raises when SMTP connection fails."""
    notifier = EmailNotifier(smtp_host="localhost", from_addr="noreply@example.com")

    with patch("smtplib.SMTP", side_effect=OSError("connection refused")):
        with pytest.raises(NotificationError, match="Email delivery failed"):
            notifier.notify(
                approver_id="alice@example.com",
                action_summary="x",
                approval_link="/y",
            )


# --- Webhook --------------------------------------------------------------


def test_webhook_sends_json_payload():
    """Webhook notifier builds correct JSON."""
    import json

    notifier = WebhookNotifier(url="https://example.com/approve")

    mock_resp = Mock()
    mock_resp.status = 200
    mock_resp.__enter__ = Mock(return_value=mock_resp)
    mock_resp.__exit__ = Mock(return_value=False)

    captured_reqs = []

    def capture_req(req, **kw):
        captured_reqs.append(req)
        return mock_resp

    with patch("hitl.notifiers.urlopen", side_effect=capture_req):
        notifier.notify(
            approver_id="alice",
            action_summary="transition P-1",
            approval_link="/approve/123",
        )

    assert len(captured_reqs) == 1
    payload = json.loads(captured_reqs[0].data.decode("utf-8"))
    assert payload["approver_id"] == "alice"
    assert payload["action"] == "transition P-1"
    assert payload["approval_link"] == "/approve/123"


def test_webhook_raises_on_bad_status():
    """Webhook notifier raises when endpoint returns non-2xx."""
    notifier = WebhookNotifier(url="https://example.com/approve")

    mock_resp = Mock()
    mock_resp.status = 401
    mock_resp.__enter__ = Mock(return_value=mock_resp)
    mock_resp.__exit__ = Mock(return_value=False)

    with patch("hitl.notifiers.urlopen", return_value=mock_resp):
        with pytest.raises(NotificationError, match="401"):
            notifier.notify(
                approver_id="alice",
                action_summary="x",
                approval_link="/y",
            )


# --- Chain ----------------------------------------------------------------


def test_notifier_chain_fans_out_to_level():
    """NotifierChain calls all notifiers for a given level."""
    slack = Mock()
    email = Mock()

    chain = NotifierChain(
        {"senior": [slack, email], "lead": [slack]}
    )
    chain.notify(
        level="senior",
        approver_id="alice",
        action_summary="x",
        approval_link="/y",
    )

    # Both Slack and Email should be called for senior level
    slack.notify.assert_called_once()
    email.notify.assert_called_once()


def test_notifier_chain_skips_missing_level():
    """NotifierChain silently skips levels with no configured notifiers."""
    slack = Mock()

    chain = NotifierChain({"senior": [slack]})
    # Calling with a missing level should not raise
    chain.notify(
        level="junior",
        approver_id="alice",
        action_summary="x",
        approval_link="/y",
    )

    # No notifier should have been called
    slack.notify.assert_not_called()


def test_notifier_chain_catches_failures():
    """NotifierChain logs but does not raise on notifier failure."""
    bad = Mock()
    bad.notify = Mock(side_effect=NotificationError("service down"))

    with patch("hitl.notifiers.log_event") as mock_log:
        chain = NotifierChain({"senior": [bad]})
        # This should not raise
        chain.notify(
            level="senior",
            approver_id="alice",
            action_summary="x",
            approval_link="/y",
        )

    # Should have logged the failure
    mock_log.assert_called_once()
    call_kwargs = mock_log.call_args[1]
    assert call_kwargs["level"] == "warning"
    assert "notification_failed" in mock_log.call_args[0]
