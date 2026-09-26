"""Human-in-the-loop approval notifications.

Slack, email, and generic webhooks. Fire-and-forget: a notification failure does
not fail the approval. Configurable per-level (JUNIOR, SENIOR, LEAD).
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Protocol
from urllib.error import URLError
from urllib.request import Request, urlopen

import httpx

from hitl.logging import log_event


class NotificationError(Exception):
    """A notification could not be sent."""


class Notifier(Protocol):
    """Send a notification to a human approver."""

    def notify(self, *, approver_id: str, action_summary: str, approval_link: str) -> None:
        """Send a notification.

        Raises NotificationError if delivery fails. The caller (graph) ignores
        it and proceeds; notifications are best-effort.
        """
        ...


@dataclass
class SlackNotifier:
    """Send to Slack via webhook URL.

    Configure with `slack_webhook_url` or pass to SlackNotifier(url=...).
    """

    url: str
    """Slack incoming webhook URL."""

    def notify(self, *, approver_id: str, action_summary: str, approval_link: str) -> None:
        payload = {
            "text": f"Approval needed from {approver_id}",
            "blocks": [
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"*Approval Request*\nFrom: {approver_id}"},
                },
                {"type": "section", "text": {"type": "mrkdwn", "text": f"*Action:* {action_summary}"}},
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Approve"},
                            "url": approval_link,
                            "style": "primary",
                        }
                    ],
                },
            ],
        }

        try:
            with httpx.post(self.url, json=payload, timeout=5) as resp:
                if resp.status_code not in (200, 201):
                    raise NotificationError(
                        f"Slack returned {resp.status_code}: {resp.text}"
                    )
        except (httpx.HTTPError, httpx.TimeoutException) as exc:
            raise NotificationError(f"Slack delivery failed: {exc}") from exc


@dataclass
class EmailNotifier:
    """Send via SMTP (simplified: assumes local sendmail or relay)."""

    smtp_host: str
    """SMTP server hostname."""

    from_addr: str
    """Sender address."""

    def notify(self, *, approver_id: str, action_summary: str, approval_link: str) -> None:
        """Send a plain-text email.

        Assumes SMTP server is available and open relay is acceptable
        (typical in k8s/cloud environments where SMTP runs in-cluster).
        """
        import smtplib
        from email.mime.text import MIMEText

        body = f"""
Action: {action_summary}
Approval Link: {approval_link}

Approve at: {approval_link}
"""
        msg = MIMEText(body)
        msg["Subject"] = f"Approval needed: {action_summary[:50]}"
        msg["From"] = self.from_addr
        msg["To"] = approver_id

        try:
            with smtplib.SMTP(self.smtp_host, 25, timeout=5) as conn:
                conn.send_message(msg)
        except (smtplib.SMTPException, OSError) as exc:
            raise NotificationError(f"Email delivery failed: {exc}") from exc


@dataclass
class WebhookNotifier:
    """Send to an arbitrary HTTPS endpoint.

    POST a JSON payload with request_summary and approval_link.
    """

    url: str
    """HTTPS endpoint."""

    def notify(self, *, approver_id: str, action_summary: str, approval_link: str) -> None:
        payload = {
            "approver_id": approver_id,
            "action": action_summary,
            "approval_link": approval_link,
        }

        try:
            req = Request(
                self.url, data=json.dumps(payload).encode("utf-8"), method="POST"
            )
            req.add_header("Content-Type", "application/json")
            with urlopen(req, timeout=5) as resp:  # noqa: S310
                if resp.status not in (200, 201, 202):
                    raise NotificationError(f"Webhook returned {resp.status}")
        except URLError as exc:
            raise NotificationError(f"Webhook delivery failed: {exc}") from exc


class NotifierChain:
    """Fan-out to multiple notifiers. Failures in one do not prevent others."""

    def __init__(self, notifiers: dict[str, list[Notifier]] | None = None):
        """Notifiers by approval level: {JUNIOR: [notifier1, notifier2], ...}."""
        self.notifiers = notifiers or {}

    def notify(
        self, *, level: str, approver_id: str, action_summary: str, approval_link: str
    ) -> None:
        """Send to all notifiers for this level. Log failures, do not raise."""
        for notifier in self.notifiers.get(level, []):
            try:
                notifier.notify(
                    approver_id=approver_id,
                    action_summary=action_summary,
                    approval_link=approval_link,
                )
            except NotificationError as exc:
                # Log but do not fail the approval.
                log_event(
                    "notification_failed",
                    level="warning",
                    notifier_type=type(notifier).__name__,
                    approver=approver_id,
                    error=str(exc),
                )
