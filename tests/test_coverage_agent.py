import json

from app.agents.coverage_agent import COVERAGE_SCHEMA, check_coverage
from app.models import Claimant, Policy


def _seed(db_session, **overrides):
    claimant = Claimant(full_name="Jane Doe", national_id="ID1234567", date_of_birth="1990-01-01")
    db_session.add(claimant)
    db_session.flush()

    defaults = dict(
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
        claimed_amount_ytd=0.0,
    )
    defaults.update(overrides)
    policy = Policy(**defaults)
    db_session.add(policy)
    db_session.commit()
    return claimant, policy


def _assessment(**overrides):
    result = {
        "claimant_found": True,
        "policy_found": True,
        "policy_holder_matches_claimant": True,
        "policy_active": True,
        "claim_type_matches_policy": True,
        "incident_within_policy_period": True,
        "waiting_period_elapsed": True,
        "exclusions_clear": True,
        "remaining_coverage_available": True,
        "matched_exclusions": [],
        "is_covered": True,
        "reasoning": "The claim matches the active policy and no exclusion applies.",
    }
    return result | overrides


def _claimant_and_policy():
    return {
        "claimant_national_id": "ID1234567",
        "policy_number": "POL-00000001",
        "incident_date": "2025-06-01",
        "incident_description": "hospitalisation for appendicitis surgery",
    }


def _fake_llm(monkeypatch, response, captured=None):
    import app.agents.coverage_agent as agent

    def fake_structured_call(**kwargs):
        if captured is not None:
            captured.update(kwargs)
        return response

    monkeypatch.setattr(agent, "structured_call", fake_structured_call)


def test_clean_claim_uses_retrieved_policy_evidence_and_llm(monkeypatch, db_session):
    claimant, policy = _seed(db_session)
    captured = {}
    _fake_llm(monkeypatch, _assessment(), captured)

    result = check_coverage(db_session, _claimant_and_policy(), "health")

    prompt = json.loads(captured["user_prompt"].split("\n", 1)[1])
    assert captured["json_schema"] == COVERAGE_SCHEMA
    assert prompt["policy"]["policy_type"] == "health"
    assert prompt["policy"]["remaining_coverage"] == 500000.0
    assert result["is_covered"] is True
    assert result["claimant_id"] == claimant.id
    assert result["policy_id"] == policy.id
    assert result["deductible"] == 5000.0


def test_missing_policy_is_retrieved_as_evidence_and_not_covered(monkeypatch, db_session):
    _seed(db_session)
    captured = {}
    _fake_llm(monkeypatch, _assessment(
        policy_found=False,
        policy_holder_matches_claimant=False,
        policy_active=False,
        claim_type_matches_policy=False,
        incident_within_policy_period=False,
        waiting_period_elapsed=False,
        exclusions_clear=False,
        remaining_coverage_available=False,
        is_covered=False,
        reasoning="No matching policy was found.",
    ), captured)
    claim = _claimant_and_policy() | {"policy_number": "POL-DOES-NOT-EXIST"}

    result = check_coverage(db_session, claim, "health")

    prompt = json.loads(captured["user_prompt"].split("\n", 1)[1])
    assert prompt["policy_found"] is False
    assert result["is_covered"] is False
    assert result["policy_id"] is None


def test_llm_cannot_mark_claim_covered_when_required_check_fails(monkeypatch, db_session):
    _seed(db_session, status="lapsed")
    _fake_llm(monkeypatch, _assessment(policy_active=False, is_covered=True))

    result = check_coverage(db_session, _claimant_and_policy(), "health")

    assert result["is_covered"] is False
    assert result["notes"]["checks"][3]["ok"] is False


def test_llm_cannot_mark_missing_database_policy_covered(monkeypatch, db_session):
    _seed(db_session)
    _fake_llm(monkeypatch, _assessment())
    claim = _claimant_and_policy() | {"policy_number": "POL-DOES-NOT-EXIST"}

    result = check_coverage(db_session, claim, "health")

    assert result["is_covered"] is False
    assert result["policy_id"] is None


def test_llm_cannot_override_database_policy_holder_mismatch(monkeypatch, db_session):
    _, policy = _seed(db_session)
    other_claimant = Claimant(
        full_name="Alex Example",
        national_id="ID7654321",
        date_of_birth="1990-01-01",
    )
    db_session.add(other_claimant)
    db_session.flush()
    policy.holder_id = other_claimant.id
    db_session.commit()
    _fake_llm(monkeypatch, _assessment())

    result = check_coverage(db_session, _claimant_and_policy(), "health")

    assert result["is_covered"] is False
    assert result["notes"]["checks"][2]["result"] == "mismatch"


def test_model_can_flag_policy_period_waiting_period_or_exclusion(monkeypatch, db_session):
    _seed(db_session)
    _fake_llm(monkeypatch, _assessment(
        incident_within_policy_period=False,
        waiting_period_elapsed=False,
        exclusions_clear=False,
        matched_exclusions=["cosmetic surgery"],
        is_covered=False,
        reasoning="The incident date is outside the covered period and an exclusion applies.",
    ))

    result = check_coverage(db_session, _claimant_and_policy(), "health")

    assert result["is_covered"] is False
    assert result["notes"]["checks"][5]["result"] == "fail"
    assert result["notes"]["checks"][6]["result"] == "fail"
    assert result["notes"]["checks"][7]["result"] == "matched"


def test_claim_type_mismatch_is_included_in_llm_assessment(monkeypatch, db_session):
    _seed(db_session)
    captured = {}
    _fake_llm(monkeypatch, _assessment(
        claim_type_matches_policy=False,
        is_covered=False,
        reasoning="The auto claim does not match the health policy.",
    ), captured)

    result = check_coverage(db_session, _claimant_and_policy(), "auto")

    prompt = json.loads(captured["user_prompt"].split("\n", 1)[1])
    assert prompt["claim_type"] == "auto"
    assert result["is_covered"] is False
