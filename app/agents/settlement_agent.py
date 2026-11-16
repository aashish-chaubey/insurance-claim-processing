"""Settlement Agent: deterministic. Calculates the proposed settlement amount,
recommends approve/reject/investigate, and proposes (but never silently
executes) a ClaimDecision with an idempotency key so re-running the pipeline
never double-books a decision."""

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import ClaimDecision, DecisionStatus, Policy
from app.security import make_idempotency_key, requires_human_approval

settings = get_settings()


def recommend_decision(
    *,
    is_covered: bool,
    coverage_notes: dict,
    fraud_score: float,
    missing_documents: list,
    invoice_amount: float | None,
    deductible: float,
    remaining_coverage: float,
) -> dict:
    reasons: list[str] = []

    if not is_covered:
        decision_type = "reject"
        reasons.append("not_covered: " + "; ".join(
            c["check"]
            for c in coverage_notes.get("checks", [])
            if c.get("result") in ("mismatch", "fail", "not_found") or c.get("ok") is False
        ))
        amount = 0.0
    elif fraud_score >= settings.fraud_score_requires_investigation:
        decision_type = "investigate"
        reasons.append(f"fraud_score_{fraud_score:.2f}_at_or_above_threshold_{settings.fraud_score_requires_investigation}")
        amount = 0.0
    elif missing_documents:
        decision_type = "investigate"
        reasons.append(f"missing_documents: {missing_documents}")
        amount = 0.0
    else:
        decision_type = "approve"
        raw_amount = (invoice_amount or 0.0) - deductible
        amount = max(0.0, min(raw_amount, remaining_coverage))
        reasons.append(f"invoice={invoice_amount} - deductible={deductible}, capped at remaining_coverage={remaining_coverage}")

    return {"decision_type": decision_type, "amount": round(amount, 2), "reasons": reasons}


def propose_decision(
    db: Session, *, claim_id: str, decision_type: str, amount: float, confidence: float, fraud_score: float
) -> tuple[ClaimDecision, bool]:
    idem_key = make_idempotency_key(claim_id, decision_type)

    existing = db.query(ClaimDecision).filter_by(idempotency_key=idem_key).one_or_none()
    if existing:
        return existing, False

    needs_approval = requires_human_approval(
        decision_type,
        confidence=confidence,
        low_confidence_threshold=settings.low_confidence_threshold,
        fraud_score=fraud_score,
        fraud_threshold=settings.fraud_score_requires_investigation,
        amount=amount if decision_type == "approve" else None,
        auto_approve_max=settings.settlement_auto_approve_max,
    )

    decision = ClaimDecision(
        claim_id=claim_id,
        decision_type=decision_type,
        amount=amount,
        idempotency_key=idem_key,
        status=DecisionStatus.PROPOSED.value,
        requested_by="settlement_agent",
    )
    db.add(decision)
    db.flush()
    return decision, needs_approval


def execute_decision(db: Session, decision: ClaimDecision, policy_id: str | None) -> ClaimDecision:
    """Apply an approved settlement decision. In production this would call a
    payment gateway / claims platform; here it increments the policy's
    claimed_amount_ytd as a stand-in so the effect on remaining coverage is
    observable end-to-end.

    Idempotent: calling this twice on an already-executed decision is a no-op,
    so it's safe from the straight-through path, the human maker-checker path,
    or a retry, without risk of double-crediting the same settlement against
    the policy's coverage limit.
    """
    if decision.status == DecisionStatus.EXECUTED.value:
        return decision

    if decision.decision_type == "approve" and decision.amount and policy_id:
        policy = db.get(Policy, policy_id)
        if policy:
            # Additive, tied to this specific decision — never overwrites; safe when
            # multiple unrelated claims settle against the same policy concurrently.
            policy.claimed_amount_ytd = policy.claimed_amount_ytd + decision.amount

    decision.status = DecisionStatus.EXECUTED.value
    from datetime import datetime, timezone

    decision.executed_at = datetime.now(timezone.utc)
    db.flush()
    return decision
