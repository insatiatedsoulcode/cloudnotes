"""
Audit logging helper.

log_action() adds an AuditLog entry to the CURRENT session without committing.
The caller is responsible for committing — this keeps the audit entry in the same
transaction as the business action (both succeed or both fail together).

Audit rows are append-only: never UPDATE'd or DELETE'd.
"""

from typing import Any

from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog


def log_action(
    db: Session,
    *,
    action: str,
    user_id: int | None = None,
    resource_type: str | None = None,
    resource_id: int | None = None,
    details: dict[str, Any] | None = None,
    ip_address: str | None = None,
) -> None:
    db.add(AuditLog(
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details,
        ip_address=ip_address,
    ))
