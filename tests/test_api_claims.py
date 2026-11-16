import app.agents.communication_agent as communication_agent
import app.agents.document_agent as document_agent
from app.models import Claimant, Policy


def _seed(db_session):
    claimant = Claimant(full_name="Jane Doe", national_id="ID1234567", date_of_birth="1990-01-01")
    db_session.add(claimant)
    db_session.flush()
    policy = Policy(
        holder_id=claimant.id,
        policy_number="POL-00000001",
        policy_type="health",
        coverage_limit=500000.0,
        deductible=5000.0,
        start_date="2025-01-01",
        end_date="2026-01-01",
        status="active",
        waiting_period_days=30,
        exclusions=["cosmetic surgery"],
    )
    db_session.add(policy)
    db_session.commit()
    return claimant, policy


def _fake_document(*, claim_type="health", confidence=0.95, invoice_amount=20000, missing=None):
    return {
        "claim_type": claim_type,
        "priority": "normal",
        "classification_confidence": confidence,
        "claimant_full_name": "Jane Doe",
        "claimant_national_id": "ID1234567",
        "policy_number": "POL-00000001",
        "incident_date": "2025-06-01",
        "incident_description": "hospitalisation for appendicitis surgery requiring emergency treatment",
        "hospital_or_provider_name": "City Hospital",
        "vehicle_registration_number": "",
        "property_address": "",
        "invoice_amount": invoice_amount,
        "itemized_items": ["surgeon fee", "room rent"],
        "missing_documents": missing or [],
        "extraction_confidence": confidence,
    }


def _patch_llm(monkeypatch, document_result, comm_result=None):
    import app.agents.orchestrator as orchestrator

    monkeypatch.setattr(orchestrator, "process_claim_document", lambda s, b, a: document_result)
    monkeypatch.setattr(
        orchestrator,
        "check_coverage",
        lambda db, extracted, claim_type: {
            "notes": {
                "checks": [
                    {
                        "check": "claim_type_matches_policy",
                        "result": "ok" if claim_type == "health" else "mismatch",
                    }
                ],
                "is_covered": claim_type == "health",
                "all_checks_passed": claim_type == "health",
            },
            "claimant_id": None,
            "policy_id": None,
            "is_covered": claim_type == "health",
            "remaining_coverage": 500000.0,
            "deductible": 5000.0,
        },
    )
    monkeypatch.setattr(
        orchestrator,
        "assess_fraud",
        lambda *args, **kwargs: {
            "fraud_score": 0.1,
            "triggered_rules": [],
            "rationale": "Test assessment",
            "injection_hits": [],
        },
    )
    monkeypatch.setattr(
        orchestrator,
        "draft_communication",
        lambda **kw: comm_result or {"subject": "Re: Claim", "body": "We acknowledge your claim."},
    )


def test_clean_claim_is_straight_through_approved(client, db_session, monkeypatch):
    _seed(db_session)
    _patch_llm(monkeypatch, _fake_document(invoice_amount=20000))

    resp = client.post(
        "/claims",
        json={"raw_subject": "Health claim", "raw_body": "hospitalised", "attachments_text": ""},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["recommended_decision"] == "approve"
    assert body["status"] == "executed"
    assert body["straight_through"] is True
    assert body["proposed_settlement_amount"] == 15000.0  # 20000 - 5000 deductible


def test_missing_documents_routes_to_investigate(client, db_session, monkeypatch):
    _seed(db_session)
    _patch_llm(monkeypatch, _fake_document(missing=["discharge summary"]))

    resp = client.post(
        "/claims",
        json={"raw_subject": "Health claim", "raw_body": "hospitalised", "attachments_text": ""},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["recommended_decision"] == "investigate"
    assert body["status"] == "pending_approval"
    assert body["straight_through"] is False

    pending = client.get("/decisions/pending").json()
    assert len(pending) == 1
    decision_id = pending[0]["id"]

    review = client.post(
        f"/decisions/{decision_id}/review",
        json={"decision": "approve", "decided_by": "reviewer@insurer.example", "notes": "docs received offline"},
    )
    assert review.status_code == 200
    assert review.json()["status"] == "executed"


def test_uncovered_claim_is_rejected_via_review(client, db_session, monkeypatch):
    _seed(db_session)
    # claim type doesn't match the seeded health policy -> not covered -> reject
    _patch_llm(monkeypatch, _fake_document(claim_type="auto"))

    resp = client.post(
        "/claims",
        json={"raw_subject": "Auto claim", "raw_body": "accident", "attachments_text": ""},
    )
    body = resp.json()
    assert body["recommended_decision"] == "reject"
    assert body["status"] == "pending_approval"

    pending = client.get("/decisions/pending").json()
    decision_id = pending[0]["id"]

    review = client.post(
        f"/decisions/{decision_id}/review",
        json={"decision": "reject", "decided_by": "reviewer@insurer.example", "notes": "confirmed not covered"},
    )
    assert review.status_code == 200
    assert review.json()["status"] == "rejected"

    # double-decision guard
    resp2 = client.post(
        f"/decisions/{decision_id}/review",
        json={"decision": "approve", "decided_by": "reviewer@insurer.example", "notes": "oops"},
    )
    assert resp2.status_code == 409
