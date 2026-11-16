from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.orchestrator import run_pipeline
from app.db import get_db
from app.models import Claim
from app.schemas import ClaimIn, ClaimOut
from app.security import new_claim_number

router = APIRouter(prefix="/claims", tags=["claims"])


@router.post("", response_model=ClaimOut)
def create_claim(payload: ClaimIn, run_now: bool = True, db: Session = Depends(get_db)):
    claim = Claim(
        claim_number=new_claim_number(),
        channel=payload.channel,
        source=payload.source,
        raw_subject=payload.raw_subject,
        raw_body=payload.raw_body,
        attachments_text=payload.attachments_text,
    )
    db.add(claim)
    db.commit()
    db.refresh(claim)

    if run_now:
        claim = run_pipeline(db, claim)

    return claim


@router.get("", response_model=list[ClaimOut])
def list_claims(status: str | None = None, limit: int = 50, db: Session = Depends(get_db)):
    stmt = select(Claim).order_by(Claim.created_at.desc()).limit(limit)
    if status:
        stmt = stmt.where(Claim.status == status)
    return db.execute(stmt).scalars().all()


@router.get("/{claim_id}")
def get_claim(claim_id: str, db: Session = Depends(get_db)):
    claim = db.get(Claim, claim_id)
    if not claim:
        raise HTTPException(404, "claim not found")
    return {
        "claim": ClaimOut.model_validate(claim),
        "extracted_data": claim.extracted_data,
        "coverage_notes": claim.coverage_notes,
        "fraud_notes": claim.fraud_notes,
        "decisions": [
            {
                "id": d.id,
                "decision_type": d.decision_type,
                "status": d.status,
                "amount": d.amount,
                "approved_by": d.approved_by,
            }
            for d in claim.decisions
        ],
        "communications": [{"id": c.id, "text": c.draft_text, "status": c.status} for c in claim.communications],
    }


@router.post("/{claim_id}/rerun", response_model=ClaimOut)
def rerun_claim(claim_id: str, db: Session = Depends(get_db)):
    claim = db.get(Claim, claim_id)
    if not claim:
        raise HTTPException(404, "claim not found")
    claim = run_pipeline(db, claim)
    return claim
