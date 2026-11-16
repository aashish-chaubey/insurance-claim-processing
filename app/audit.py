from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditLog
from app.security import hash_audit_record


def log_event(db: Session, *, claim_id: str | None, actor: str, event_type: str, event_data: dict) -> AuditLog:
    last = db.execute(
        select(AuditLog).order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(1)
    ).scalar_one_or_none()
    prev_hash = last.record_hash if last else "genesis"
    record_hash = hash_audit_record(prev_hash, actor, event_type, event_data)

    entry = AuditLog(
        claim_id=claim_id,
        actor=actor,
        event_type=event_type,
        event_data=event_data,
        prev_hash=prev_hash,
        record_hash=record_hash,
    )
    db.add(entry)
    db.flush()
    return entry
