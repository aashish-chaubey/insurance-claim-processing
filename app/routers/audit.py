from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import AuditLog

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("")
def list_audit(claim_id: str | None = None, limit: int = 200, db: Session = Depends(get_db)):
    stmt = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)
    if claim_id:
        stmt = stmt.where(AuditLog.claim_id == claim_id)
    rows = db.execute(stmt).scalars().all()
    return [
        {
            "id": r.id,
            "claim_id": r.claim_id,
            "actor": r.actor,
            "event_type": r.event_type,
            "event_data": r.event_data,
            "created_at": r.created_at,
            "prev_hash": r.prev_hash,
            "record_hash": r.record_hash,
        }
        for r in rows
    ]


@router.get("/verify_chain")
def verify_chain(db: Session = Depends(get_db)):
    """Re-derives each record's hash from (prev_hash, actor, event_type,
    event_data) and confirms the chain is intact and untampered."""
    from app.security import hash_audit_record

    rows = db.execute(select(AuditLog).order_by(AuditLog.created_at.asc(), AuditLog.id.asc())).scalars().all()
    broken_at = None
    for r in rows:
        expected = hash_audit_record(r.prev_hash, r.actor, r.event_type, r.event_data)
        if expected != r.record_hash:
            broken_at = r.id
            break
    return {"total_records": len(rows), "chain_intact": broken_at is None, "broken_at_record": broken_at}
