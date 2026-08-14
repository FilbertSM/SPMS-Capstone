"""Telegram Bot API integration for alert-triggered notifications.

Two independent responsibilities live here:
  - sending alert messages to linked, eligible users (`dispatch_alert_notifications`,
    called as a FastAPI BackgroundTask so it never blocks the ML prediction request)
  - long-polling for `/start <token>` updates to complete a user's self-service
    account-linking flow (`run_link_listener_forever`, started once at app startup)

Plain httpx calls against the Telegram Bot API are used instead of a Telegram SDK -
the two operations needed (sendMessage, getUpdates) are simple HTTP calls, and
httpx is already a project dependency.
"""
import asyncio
import json
import re
from datetime import datetime, timezone

import httpx
from sqlalchemy.orm import Session

from app.core.audit import append_audit_log
from app.core.config import settings
from app.database import models
from app.database.database import SessionLocal

NOTIFICATION_SETTINGS_KEY = "telegram_notification_settings"
SEVERITY_RANK = {"normal": 0, "warning": 1, "critical": 2}

_START_COMMAND_RE = re.compile(r"^/start\s+(\S+)$")


def _api_url(method: str) -> str:
    return f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/{method}"


async def send_telegram_message(chat_id: str, text: str) -> tuple[bool, str | None, str | None]:
    """POST sendMessage. Never raises - always returns a clean (success, message_id, error) tuple."""
    if not settings.TELEGRAM_BOT_TOKEN:
        return False, None, "TELEGRAM_BOT_TOKEN is not configured"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                _api_url("sendMessage"),
                json={"chat_id": chat_id, "text": text},
            )
        payload = response.json()
        if response.status_code == 200 and payload.get("ok"):
            return True, str(payload["result"]["message_id"]), None
        return False, None, payload.get("description", f"HTTP {response.status_code}")
    except (httpx.HTTPError, ValueError) as exc:
        return False, None, str(exc)


def notification_settings_state(db: Session) -> dict:
    setting = (
        db.query(models.RuntimeSetting)
        .filter(models.RuntimeSetting.key == NOTIFICATION_SETTINGS_KEY)
        .first()
    )
    if setting is None:
        return {
            "enabled": False,
            "min_severity": "critical",
            "reason": None,
            "updated_by": None,
            "updated_at": None,
        }
    try:
        payload = json.loads(setting.value_json)
    except (TypeError, json.JSONDecodeError):
        payload = {}
    return {
        "enabled": bool(payload.get("enabled", False)),
        "min_severity": payload.get("min_severity", "critical"),
        "reason": setting.reason,
        "updated_by": setting.updated_by,
        "updated_at": setting.updated_at,
    }


def dispatch_alert_notifications(
    anomaly_event_id: int,
    machine_id: str,
    severity: str,
    message_text: str,
) -> None:
    """Send the alert to every eligible, linked, enabled user and log each attempt.

    Runs as a FastAPI BackgroundTask (own DB session, executed after the response
    is sent) so a slow or failed Telegram call can never delay or break anomaly
    detection. Never raises.
    """
    db = SessionLocal()
    try:
        state = notification_settings_state(db)
        if not state["enabled"]:
            return
        if SEVERITY_RANK.get(severity, 0) < SEVERITY_RANK.get(state["min_severity"], 2):
            return

        recipients = (
            db.query(models.User)
            .filter(
                models.User.notify_eligible.is_(True),
                models.User.telegram_notifications_enabled.is_(True),
                models.User.telegram_chat_id.isnot(None),
            )
            .all()
        )
        if not recipients:
            return

        async def _send_all():
            return [
                (user,) + await send_telegram_message(user.telegram_chat_id, message_text)
                for user in recipients
            ]

        results = asyncio.run(_send_all())

        for user, success, message_id, error_detail in results:
            db.add(
                models.NotificationLog(
                    anomaly_event_id=anomaly_event_id,
                    user_id=user.id,
                    user_email=user.email,
                    channel="telegram",
                    status="sent" if success else "failed",
                    severity=severity,
                    machine_id=machine_id,
                    error_detail=error_detail,
                    telegram_message_id=message_id,
                )
            )
        db.commit()
    except Exception as exc:  # noqa: BLE001 - background task must never raise
        print(f"WARNING: alert notification dispatch failed: {exc}")
        db.rollback()
    finally:
        db.close()


async def _handle_start_command(db: Session, chat_id: int, text: str) -> None:
    match = _START_COMMAND_RE.match(text.strip())
    if not match:
        return

    token = match.group(1)
    now = datetime.now(timezone.utc)
    user = (
        db.query(models.User)
        .filter(
            models.User.telegram_link_token == token,
            models.User.telegram_link_token_expires.isnot(None),
            models.User.telegram_link_token_expires > now,
        )
        .first()
    )
    if user is None:
        await send_telegram_message(
            str(chat_id),
            "This SPMS linking code is invalid or has expired. Generate a new one from your SPMS profile page.",
        )
        return

    user.telegram_chat_id = str(chat_id)
    user.telegram_linked_at = now
    user.telegram_link_token = None
    user.telegram_link_token_expires = None
    user.telegram_notifications_enabled = True
    db.commit()

    append_audit_log(
        db,
        user_email=user.email,
        action="TELEGRAM_LINK_COMPLETED",
        status_value="SUCCESS",
        ip_address=None,
        browser_info="telegram-bot-listener",
    )
    db.commit()

    await send_telegram_message(
        str(chat_id),
        "Your Telegram account is now linked to SPMS. You'll receive alert notifications here when enabled.",
    )


async def _poll_once(client: httpx.AsyncClient, offset: int | None) -> tuple[list[dict], int | None]:
    params: dict = {"timeout": settings.TELEGRAM_POLL_TIMEOUT_SECONDS}
    if offset is not None:
        params["offset"] = offset

    response = await client.get(
        _api_url("getUpdates"),
        params=params,
        timeout=settings.TELEGRAM_POLL_TIMEOUT_SECONDS + 10,
    )
    payload = response.json()
    if not payload.get("ok"):
        return [], offset

    updates = payload.get("result", [])
    next_offset = offset
    for update in updates:
        next_offset = update["update_id"] + 1
    return updates, next_offset


async def run_link_listener_forever() -> None:
    """Long-poll Telegram getUpdates and complete /start <token> account links.

    Wrapped in its own try/except loop so a transient Telegram API hiccup never
    kills the background task; used no-webhook is required because local/docker-compose
    dev has no public HTTPS endpoint to receive Telegram webhook callbacks.
    """
    if not settings.TELEGRAM_BOT_TOKEN:
        print("WARNING: TELEGRAM_BOT_TOKEN not set - Telegram link listener will not start.")
        return

    offset: int | None = None
    async with httpx.AsyncClient() as client:
        while True:
            try:
                updates, offset = await _poll_once(client, offset)
                for update in updates:
                    message = update.get("message")
                    if not message or "text" not in message:
                        continue
                    chat_id = message["chat"]["id"]
                    db = SessionLocal()
                    try:
                        await _handle_start_command(db, chat_id, message["text"])
                    finally:
                        db.close()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - poller must survive transient errors
                print(f"WARNING: Telegram link listener error: {exc}")
                await asyncio.sleep(5)
