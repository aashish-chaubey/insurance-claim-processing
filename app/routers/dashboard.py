from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Claim, ClaimDecision, Policy
from app.routers.decisions import review_decision
from app.schemas import DecisionReviewIn
from app.security import mask_identifier

router = APIRouter(tags=["dashboard"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/")
def dashboard_home(request: Request, db: Session = Depends(get_db)):
    claims = db.execute(select(Claim).order_by(Claim.created_at.desc()).limit(100)).scalars().all()
    counts = {}
    for c in claims:
        counts[c.status] = counts.get(c.status, 0) + 1
    return templates.TemplateResponse(
        "claims_list.html", {"request": request, "claims": claims, "counts": counts}
    )


@router.get("/review")
def review_queue(request: Request, db: Session = Depends(get_db)):
    decisions = db.execute(select(ClaimDecision).where(ClaimDecision.status == "pending_approval")).scalars().all()
    rows = []
    for d in decisions:
        claim = db.get(Claim, d.claim_id)
        policy = db.get(Policy, claim.policy_id) if claim and claim.policy_id else None
        rows.append(
            {
                "decision": d,
                "claim": claim,
                "masked_policy": mask_identifier(policy.policy_number) if policy else "N/A",
            }
        )
    return templates.TemplateResponse("review_queue.html", {"request": request, "rows": rows})


@router.post("/review/{decision_id}/decide")
def review_decide(
    decision_id: str,
    decision: str = Form(...),
    decided_by: str = Form("claims_reviewer@insurer.example"),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    review_decision(decision_id, DecisionReviewIn(decision=decision, decided_by=decided_by, notes=notes), db)
    return RedirectResponse(url="/review", status_code=303)


@router.get("/claims/{claim_id}/view")
def claim_view(request: Request, claim_id: str, db: Session = Depends(get_db)):
    claim = db.get(Claim, claim_id)
    return templates.TemplateResponse("claim_detail.html", {"request": request, "claim": claim})
