"""Orchestrator: planner/coordinator that runs the agent team end-to-end for a
single claim: Claim Intake -> Document -> Coverage -> Fraud -> Settlement ->
Communication, persisting state and an audit trail at every step. Mirrors the
AGENT TEAM sequence in the project catalogue."""

import logging

from sqlalchemy.orm import Session

from app.agents.communication_agent import draft_communication
from app.agents.coverage_agent import check_coverage
from app.agents.document_agent import process_claim_document
from app.agents.fraud_agent import assess_fraud
from app.agents.settlement_agent import execute_decision, propose_decision, recommend_decision
from app.audit import log_event
from app.models import Claim, ClaimStatus, CommunicationDraft, Policy
from app.security import mask_identifier

logger = logging.getLogger("claims.orchestrator")


class PipelineException(Exception):
    def __init__(self, stage: str, reason: str):
        self.stage = stage
        self.reason = reason
        super().__init__(f"{stage}: {reason}")


def run_pipeline(db: Session, claim: Claim) -> Claim:
    """Run the full agent pipeline for one claim. Any stage failure routes the
    claim to ClaimStatus.EXCEPTION with a recorded reason rather than raising
    past the caller, so a batch run can continue past a single bad claim."""
    try:
        _intake(db, claim)
        _document(db, claim)
        _coverage(db, claim)
        _fraud(db, claim)
        _settlement(db, claim)
        _communicate(db, claim)
        db.commit()
    except PipelineException as exc:
        db.rollback()
        claim = db.merge(claim)
        claim.status = ClaimStatus.EXCEPTION.value
        claim.exception_reason = f"{exc.stage}: {exc.reason}"
        log_event(
            db,
            claim_id=claim.id,
            actor="orchestrator",
            event_type="pipeline_exception",
            event_data={"stage": exc.stage, "reason": exc.reason},
        )
        db.commit()
    return claim


def _intake(db: Session, claim: Claim) -> None:
    log_event(
        db,
        claim_id=claim.id,
        actor="claim_intake_agent",
        event_type="claim_received",
        event_data={"channel": claim.channel, "source": claim.source, "subject": claim.raw_subject},
    )
    claim.status = ClaimStatus.RECEIVED.value
    db.flush()


def _document(db: Session, claim: Claim) -> None:
    try:
        result = process_claim_document(claim.raw_subject, claim.raw_body, claim.attachments_text)
    except Exception as exc:  # noqa: BLE001
        raise PipelineException("document", str(exc)) from exc

    claim.claim_type = result["claim_type"]
    claim.priority = result["priority"]
    claim.classification_confidence = result["classification_confidence"]
    claim.extracted_data = result
    claim.extraction_confidence = result["extraction_confidence"]
    claim.status = ClaimStatus.EXTRACTED.value

    redacted = {**result, "claimant_national_id": mask_identifier(result.get("claimant_national_id", ""))}
    log_event(db, claim_id=claim.id, actor="document_agent", event_type="document_processed", event_data=redacted)
    db.flush()


def _coverage(db: Session, claim: Claim) -> None:
    try:
        result = check_coverage(db, claim.extracted_data, claim.claim_type)
    except Exception as exc:  # noqa: BLE001
        raise PipelineException("coverage", str(exc)) from exc
    claim.claimant_id = result["claimant_id"]
    claim.policy_id = result["policy_id"]
    claim.coverage_notes = {
        **result["notes"],
        "deductible": result.get("deductible", 0.0),
        "remaining_coverage": result.get("remaining_coverage", 0.0),
    }
    claim.status = ClaimStatus.COVERAGE_CHECKED.value
    log_event(db, claim_id=claim.id, actor="coverage_agent", event_type="coverage_checked", event_data=claim.coverage_notes)
    db.flush()


def _fraud(db: Session, claim: Claim) -> None:
    policy = db.get(Policy, claim.policy_id) if claim.policy_id else None
    try:
        result = assess_fraud(
            db,
            claim_id=claim.id,
            policy_id=claim.policy_id,
            extracted=claim.extracted_data,
            policy_start_date=policy.start_date if policy else None,
            remaining_coverage=claim.coverage_notes.get("remaining_coverage") if claim.coverage_notes else None,
            raw_body=claim.raw_body,
            raw_attachments=claim.attachments_text,
        )
    except Exception as exc:  # noqa: BLE001
        raise PipelineException("fraud", str(exc)) from exc
    claim.fraud_notes = result
    claim.fraud_score = result["fraud_score"]
    claim.status = ClaimStatus.FRAUD_CHECKED.value
    log_event(db, claim_id=claim.id, actor="fraud_agent", event_type="fraud_assessed", event_data=result)
    db.flush()


def _settlement(db: Session, claim: Claim) -> None:
    coverage_notes = claim.coverage_notes or {}
    recommendation = recommend_decision(
        is_covered=bool(coverage_notes.get("is_covered")),
        coverage_notes=coverage_notes,
        fraud_score=claim.fraud_score,
        missing_documents=claim.extracted_data.get("missing_documents") or [],
        invoice_amount=claim.extracted_data.get("invoice_amount"),
        deductible=coverage_notes.get("deductible", 0.0),
        remaining_coverage=coverage_notes.get("remaining_coverage", 0.0),
    )
    claim.recommended_decision = recommendation["decision_type"]
    claim.proposed_settlement_amount = recommendation["amount"]
    claim.status = ClaimStatus.DECISION_PROPOSED.value
    log_event(db, claim_id=claim.id, actor="settlement_agent", event_type="decision_recommended", event_data=recommendation)

    combined_confidence = min(claim.classification_confidence, claim.extraction_confidence)
    decision, needs_approval = propose_decision(
        db,
        claim_id=claim.id,
        decision_type=recommendation["decision_type"],
        amount=recommendation["amount"],
        confidence=combined_confidence,
        fraud_score=claim.fraud_score,
    )
    claim.straight_through = not needs_approval
    log_event(
        db,
        claim_id=claim.id,
        actor="settlement_agent",
        event_type="decision_proposed",
        event_data={"decision_id": decision.id, "decision_type": decision.decision_type, "needs_approval": needs_approval},
    )

    if needs_approval:
        claim.status = ClaimStatus.PENDING_APPROVAL.value
        decision.status = "pending_approval"
    else:
        claim.status = ClaimStatus.EXECUTED.value
        decision.approved_by = "system_straight_through"
        execute_decision(db, decision, claim.policy_id)
        log_event(
            db,
            claim_id=claim.id,
            actor="system_straight_through",
            event_type="decision_approved_and_executed",
            event_data={"decision_id": decision.id},
        )
    db.flush()


def _communicate(db: Session, claim: Claim) -> None:
    policy = db.get(Policy, claim.policy_id) if claim.policy_id else None
    masked_policy = mask_identifier(policy.policy_number) if policy else "N/A"
    claimant_name = (claim.extracted_data or {}).get("claimant_full_name", "Policyholder")

    outcome_status = "decided and executed" if claim.status == ClaimStatus.EXECUTED.value else "received and pending internal review"

    try:
        draft = draft_communication(
            claim_number=claim.claim_number,
            claimant_name=claimant_name,
            decision_type=claim.recommended_decision,
            outcome_status=outcome_status,
            masked_policy_number=masked_policy,
            settlement_amount=claim.proposed_settlement_amount if claim.status == ClaimStatus.EXECUTED.value else None,
            missing_documents=claim.extracted_data.get("missing_documents") or [],
            notes="; ".join(claim.fraud_notes.get("triggered_rules") or []),
        )
    except Exception as exc:  # noqa: BLE001
        raise PipelineException("communication", str(exc)) from exc

    comm = CommunicationDraft(
        claim_id=claim.id, draft_text=f"Subject: {draft['subject']}\n\n{draft['body']}", status="draft"
    )
    db.add(comm)
    log_event(db, claim_id=claim.id, actor="communication_agent", event_type="communication_drafted", event_data=draft)
    db.flush()
