from app.agents.settlement_agent import execute_decision, recommend_decision
from app.models import Claimant, ClaimDecision, DecisionStatus, Policy


def test_recommend_reject_when_not_covered():
    rec = recommend_decision(
        is_covered=False,
        coverage_notes={"checks": [{"check": "policy_active", "result": "lapsed"}]},
        fraud_score=0.0,
        missing_documents=[],
        invoice_amount=10000,
        deductible=1000,
        remaining_coverage=50000,
    )
    assert rec["decision_type"] == "reject"
    assert rec["amount"] == 0.0


def test_recommend_investigate_on_high_fraud_score():
    rec = recommend_decision(
        is_covered=True,
        coverage_notes={"checks": []},
        fraud_score=0.8,
        missing_documents=[],
        invoice_amount=10000,
        deductible=1000,
        remaining_coverage=50000,
    )
    assert rec["decision_type"] == "investigate"


def test_recommend_investigate_on_missing_documents():
    rec = recommend_decision(
        is_covered=True,
        coverage_notes={"checks": []},
        fraud_score=0.0,
        missing_documents=["photos of damage"],
        invoice_amount=10000,
        deductible=1000,
        remaining_coverage=50000,
    )
    assert rec["decision_type"] == "investigate"


def test_recommend_approve_amount_capped_at_remaining_coverage():
    rec = recommend_decision(
        is_covered=True,
        coverage_notes={"checks": []},
        fraud_score=0.0,
        missing_documents=[],
        invoice_amount=100000,
        deductible=1000,
        remaining_coverage=50000,
    )
    assert rec["decision_type"] == "approve"
    assert rec["amount"] == 50000.0  # capped, not 99000


def test_execute_decision_is_idempotent_and_additive(db_session):
    claimant = Claimant(full_name="Jane Doe", national_id="ID1", date_of_birth="1990-01-01")
    db_session.add(claimant)
    db_session.flush()
    policy = Policy(
        holder_id=claimant.id, policy_number="POL-1", policy_type="health",
        coverage_limit=100000.0, deductible=1000.0, claimed_amount_ytd=10000.0,
    )
    db_session.add(policy)
    db_session.flush()

    decision = ClaimDecision(
        claim_id="claim-1", decision_type="approve", amount=5000.0,
        idempotency_key="k1", status=DecisionStatus.APPROVED.value,
    )
    db_session.add(decision)
    db_session.flush()

    execute_decision(db_session, decision, policy.id)
    assert policy.claimed_amount_ytd == 15000.0
    assert decision.status == DecisionStatus.EXECUTED.value

    # calling again must be a no-op (idempotent) — no double-credit
    execute_decision(db_session, decision, policy.id)
    assert policy.claimed_amount_ytd == 15000.0
