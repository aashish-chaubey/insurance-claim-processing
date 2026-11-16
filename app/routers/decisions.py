from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.settlement_agent import execute_decision
from app.audit import log_event
from app.db import get_db
from app.models import Claim, ClaimDecision, ClaimStatus
from app.schemas import DecisionReviewIn

router = APIRouter(prefix="/decisions", tags=["decisions"])


@router.get("/pending")
def list_pending(db: Session = Depends(get_db)):
    decisions = db.execute(select(ClaimDecision).where(ClaimDecision.status == "pending_approval")).scalars().all()
    return [
        {
            "id": d.id,
            "claim_id": d.claim_id,
            "decision_type": d.decision_type,
            "amount": d.amount,
            "created_at": d.created_at,
        }
        for d in decisions
    ]


@router.post("/{decision_id}/review")
def review_decision(decision_id: str, payload: DecisionReviewIn, db: Session = Depends(get_db)):
    decision = db.get(ClaimDecision, decision_id)
    if not decision:
        raise HTTPException(404, "decision not found")
    if decision.status not in ("pending_approval", "proposed"):
        raise HTTPException(409, f"decision already in terminal state: {decision.status}")

    claim = db.get(Claim, decision.claim_id)

    if payload.decision == "approve":
        decision.status = "approved"
        decision.approved_by = payload.decided_by
        decision.decided_at = datetime.now(timezone.utc)
        execute_decision(db, decision, claim.policy_id)
        claim.status = ClaimStatus.EXECUTED.value
        log_event(
            db,
            claim_id=claim.id,
            actor=payload.decided_by,
            event_type="decision_approved_and_executed",
            event_data={"decision_id": decision.id, "notes": payload.notes},
        )
    elif payload.decision == "reject":
        decision.status = "rejected"
        decision.rejection_reason = payload.notes
        decision.decided_at = datetime.now(timezone.utc)
        claim.status = ClaimStatus.REJECTED.value
        log_event(
            db,
            claim_id=claim.id,
            actor=payload.decided_by,
            event_type="decision_rejected",
            event_data={"decision_id": decision.id, "notes": payload.notes},
        )
    else:
        raise HTTPException(400, "decision must be 'approve' or 'reject'")

    db.commit()
    return {"id": decision.id, "status": decision.status}
