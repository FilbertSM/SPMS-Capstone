"""SHA-256 hash-chain primitives for the tamper-evident audit log.

Extracted from app/main.py so that background services (e.g. the Telegram
link listener in app/services/telegram_service.py) can append audit entries
without importing app.main and creating a circular import.
"""
import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.database import models

AUDIT_HASH_ALGORITHM = "SHA-256"
AUDIT_HASH_PAYLOAD_VERSION = "audit-v1"

# MySQL/MariaDB error codes worth retrying at the caller level: 1213 = deadlock, 1205 = lock wait timeout.
RETRYABLE_LOCK_ERROR_CODES = {1213, 1205}


def is_retryable_lock_error(exc: Exception) -> bool:
    orig_args = getattr(getattr(exc, "orig", None), "args", ())
    return bool(orig_args) and orig_args[0] in RETRYABLE_LOCK_ERROR_CODES


def format_audit_timestamp(value: datetime | None) -> str:
    if value is None:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")


def canonical_audit_payload(log: models.AuditLog) -> str:
    payload = {
        "id": log.id,
        "timestamp": format_audit_timestamp(log.timestamp),
        "user_email": log.user_email or "",
        "action": log.action or "",
        "status": log.status or "",
        "ip_address": log.ip_address or "",
        "browser_info": log.browser_info or "",
        "previous_hash": log.previous_hash or "",
        "hash_algorithm": log.hash_algorithm or AUDIT_HASH_ALGORITHM,
        "hash_payload_version": log.hash_payload_version or AUDIT_HASH_PAYLOAD_VERSION,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def calculate_audit_hash(log: models.AuditLog) -> str:
    return hashlib.sha256(canonical_audit_payload(log).encode("utf-8")).hexdigest()


def append_audit_log(
    db: Session,
    *,
    user_email: str | None,
    action: str,
    status_value: str,
    ip_address: str | None,
    browser_info: str | None,
) -> models.AuditLog:
    """Append one link in the SHA-256 audit hash chain.

    Concurrent requests race for a lock on the current last row (needed to chain
    `previous_hash`), which under MariaDB can raise a 1213 deadlock. This function
    does not retry itself - InnoDB resolves a deadlock by rolling back the entire
    victim transaction, not just the statement that lost, so a retry has to happen
    at a level that knows whether anything else in the session needs replaying too.
    See `_record_audit_log`'s `retry_on_deadlock` in app/main.py.
    """
    previous = (
        db.query(models.AuditLog)
        .filter(models.AuditLog.record_hash.isnot(None))
        .order_by(models.AuditLog.id.desc())
        .with_for_update()
        .first()
    )

    # Membuang microsecond agar sinkron dengan format default MariaDB
    current_time = datetime.now(timezone.utc).replace(microsecond=0)

    log = models.AuditLog(
        timestamp=current_time,
        user_email=user_email,
        action=action,
        status=status_value,
        ip_address=ip_address,
        browser_info=browser_info,
        previous_hash=previous.record_hash if previous else None,
        hash_algorithm=AUDIT_HASH_ALGORITHM,
        hash_payload_version=AUDIT_HASH_PAYLOAD_VERSION,
    )
    db.add(log)
    db.flush()
    log.record_hash = calculate_audit_hash(log)
    return log
