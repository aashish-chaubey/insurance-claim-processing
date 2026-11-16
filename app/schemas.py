from datetime import datetime

from pydantic import BaseModel


class ClaimIn(BaseModel):
    channel: str = "email"
    source: str = "claims-intake@insurer.example"
    raw_subject: str
    raw_body: str
    attachments_text: str = ""


class ClaimOut(BaseModel):
    id: str
    claim_number: str
    status: str
    priority: str
    claim_type: str
    classification_confidence: float
    extraction_confidence: float
    fraud_score: float
    recommended_decision: str
    proposed_settlement_amount: float | None
    straight_through: bool
    exception_reason: str
    created_at: datetime

    class Config:
        from_attributes = True


class DecisionReviewIn(BaseModel):
    decision: str  # "approve" | "reject"
    decided_by: str
    notes: str = ""
