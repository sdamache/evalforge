"""Slack webhook sender for approval notifications.

Implements fire-and-forget webhook delivery with Block Kit formatting.
Uses 5-second timeout per research.md recommendations.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from src.common.config import load_approval_config
from src.common.logging import get_logger

logger = get_logger(__name__)

# Webhook timeout in seconds (per research.md)
WEBHOOK_TIMEOUT_SECONDS = 5.0


def build_approval_payload(
    suggestion_id: str,
    action: str,
    actor: str,
    suggestion_type: Optional[str] = None,
    notes: Optional[str] = None,
    reason: Optional[str] = None,
) -> dict[str, Any]:
    """Build a Block Kit payload for Slack notification.

    Args:
        suggestion_id: The suggestion ID.
        action: The action taken (approved/rejected).
        actor: Who performed the action.
        suggestion_type: Type of suggestion (eval, guardrail, runbook).
        notes: Optional notes (for approval).
        reason: Optional reason (for rejection).

    Returns:
        Slack Block Kit payload dict.
    """
    # Emoji based on action
    emoji = ":white_check_mark:" if action == "approved" else ":x:"
    action_title = action.title()

    # Build details text
    details = f"*ID:* `{suggestion_id}`\n*Action:* {action}\n*By:* {actor}"

    if suggestion_type:
        details += f"\n*Type:* {suggestion_type}"

    if notes:
        details += f"\n*Notes:* {notes}"

    if reason:
        details += f"\n*Reason:* {reason}"

    timestamp = datetime.now(timezone.utc).isoformat()

    return {
        "text": f"{emoji} Suggestion {suggestion_id} was {action} by {actor}",
        "blocks": [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"{emoji} Suggestion {action_title}",
                    "emoji": True,
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": details,
                }
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"_{timestamp}_"
                    }
                ]
            }
        ]
    }


def build_test_payload(message: Optional[str] = None) -> dict[str, Any]:
    """Build a test message payload for webhook testing.

    Args:
        message: Optional custom message.

    Returns:
        Slack Block Kit payload dict.
    """
    text = message or "Test notification from EvalForge Approval Workflow"
    timestamp = datetime.now(timezone.utc).isoformat()

    return {
        "text": text,
        "blocks": [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": ":test_tube: Webhook Test",
                    "emoji": True,
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": text,
                }
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"_Sent at {timestamp}_"
                    }
                ]
            }
        ]
    }


async def send_slack_notification(
    webhook_url: str,
    payload: dict[str, Any],
) -> bool:
    """Send a notification to Slack via webhook.

    Fire-and-forget with 5-second timeout.
    Failures are logged but do not raise exceptions.

    Args:
        webhook_url: Slack webhook URL.
        payload: Block Kit payload dict.

    Returns:
        True if sent successfully, False otherwise.
    """
    try:
        async with httpx.AsyncClient(timeout=WEBHOOK_TIMEOUT_SECONDS) as client:
            response = await client.post(webhook_url, json=payload)

            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After", "unknown")
                logger.warning(
                    "Slack rate limited",
                    extra={"retry_after": retry_after}
                )
                return False

            if response.status_code != 200:
                logger.warning(
                    "Slack webhook failed",
                    extra={
                        "status_code": response.status_code,
                        "response": response.text[:200],
                    }
                )
                return False

            logger.info("Slack notification sent successfully")
            return True

    except httpx.TimeoutException:
        logger.warning("Slack webhook timed out (continuing)")
        return False

    except Exception as e:
        logger.error(
            "Slack webhook error",
            extra={"error": str(e)}
        )
        return False


async def send_approval_notification(
    suggestion_id: str,
    action: str,
    actor: str,
    suggestion_type: Optional[str] = None,
    notes: Optional[str] = None,
    reason: Optional[str] = None,
) -> bool:
    """Send an approval/rejection notification to Slack.

    Loads webhook URL from config. If not configured, skips silently.

    Args:
        suggestion_id: The suggestion ID.
        action: The action taken (approved/rejected).
        actor: Who performed the action.
        suggestion_type: Type of suggestion.
        notes: Optional notes (for approval).
        reason: Optional reason (for rejection).

    Returns:
        True if sent successfully or not configured, False on failure.
    """
    config = load_approval_config()
    webhook_url = config.slack_webhook_url

    if not webhook_url:
        logger.debug("SLACK_WEBHOOK_URL not configured, skipping notification")
        return True  # Not a failure if not configured

    payload = build_approval_payload(
        suggestion_id=suggestion_id,
        action=action,
        actor=actor,
        suggestion_type=suggestion_type,
        notes=notes,
        reason=reason,
    )

    return await send_slack_notification(webhook_url, payload)


async def send_test_notification(
    message: Optional[str] = None,
) -> tuple[bool, str]:
    """Send a test notification to verify webhook configuration.

    Args:
        message: Optional custom message.

    Returns:
        Tuple of (success, status_message).
    """
    config = load_approval_config()
    webhook_url = config.slack_webhook_url

    if not webhook_url:
        return False, "SLACK_WEBHOOK_URL not configured"

    payload = build_test_payload(message)
    success = await send_slack_notification(webhook_url, payload)

    if success:
        return True, "Test notification sent successfully"
    else:
        return False, "Failed to send test notification - check logs for details"
