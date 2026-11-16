import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def gen_id() -> str:
    return str(uuid.uuid4())


class ClaimType(str, enum.Enum):
    HEALTH = "health"
    AUTO = "auto"
    PROPERTY = "property"
    UNKNOWN = "unknown"


class ClaimStatus(str, enum.Enum):
    RECEIVED = "received"
    CLASSIFIED = "classified"
    EXTRACTED = "extracted"
    COVERAGE_CHECKED = "coverage_checked"
    FRAUD_CHECKED = "fraud_checked"
    DECISION_PROPOSED = "decision_proposed"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTED = "executed"
    RESPONDED = "responded"
    CLOSED = "closed"
    EXCEPTION = "exception"


class DecisionType(str, enum.Enum):
    APPROVE = "approve"
    REJECT = "reject"
    INVESTIGATE = "investigate"
    UNKNOWN = "unknown"


class DecisionStatus(str, enum.Enum):
    PROPOSED = "proposed"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTED = "executed"
    FAILED = "failed"


class Claimant(Base):
    __tablename__ = "claimants"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_id)
    full_name: Mapped[str] = mapped_column(String, nullable=False)
    national_id: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    date_of_birth: Mapped[str] = mapped_column(String, nullable=False)
    contact_email: Mapped[str] = mapped_column(String, default="")
    contact_phone: Mapped[str] = mapped_column(String, default="")

    policies: Mapped[list["Policy"]] = relationship(back_populates="holder")


class Policy(Base):
    __tablename__ = "policies"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_id)
    holder_id: Mapped[str] = mapped_column(ForeignKey("claimants.id"), nullable=False)
    policy_number: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    policy_type: Mapped[str] = mapped_column(String, default=ClaimType.HEALTH.value)
    coverage_limit: Mapped[float] = mapped_column(Float, default=0.0)
    deductible: Mapped[float] = mapped_column(Float, default=0.0)
    premium: Mapped[float] = mapped_column(Float, default=0.0)
    start_date: Mapped[str] = mapped_column(String, default="")
    end_date: Mapped[str] = mapped_column(String, default="")
    status: Mapped[str] = mapped_column(String, default="active")
    waiting_period_days: Mapped[int] = mapped_column(default=30)
    exclusions: Mapped[list] = mapped_column(JSON, default=list)

    # Cumulative amount already settled against this policy's coverage_limit for its
    # current period. Only ever incremented additively by an EXECUTED settlement
    # (never overwritten), so concurrent claims against the same policy can't clobber
    # each other's effect on remaining coverage.
    claimed_amount_ytd: Mapped[float] = mapped_column(Float, default=0.0)

    holder: Mapped["Claimant"] = relationship(back_populates="policies")


class Claim(Base):
    __tablename__ = "claims"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_id)
    claim_number: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    channel: Mapped[str] = mapped_column(String, default="email")
    source: Mapped[str] = mapped_column(String, default="claims-intake@insurer.example")
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    raw_subject: Mapped[str] = mapped_column(String, default="")
    raw_body: Mapped[str] = mapped_column(Text, default="")
    attachments_text: Mapped[str] = mapped_column(Text, default="")

    status: Mapped[str] = mapped_column(String, default=ClaimStatus.RECEIVED.value)
    priority: Mapped[str] = mapped_column(String, default="normal")

    claim_type: Mapped[str] = mapped_column(String, default=ClaimType.UNKNOWN.value)
    classification_confidence: Mapped[float] = mapped_column(Float, default=0.0)

    extracted_data: Mapped[dict] = mapped_column(JSON, default=dict)
    extraction_confidence: Mapped[float] = mapped_column(Float, default=0.0)

    policy_id: Mapped[str | None] = mapped_column(ForeignKey("policies.id"), nullable=True)
    claimant_id: Mapped[str | None] = mapped_column(ForeignKey("claimants.id"), nullable=True)

    coverage_notes: Mapped[dict] = mapped_column(JSON, default=dict)
    fraud_notes: Mapped[dict] = mapped_column(JSON, default=dict)
    fraud_score: Mapped[float] = mapped_column(Float, default=0.0)

    recommended_decision: Mapped[str] = mapped_column(String, default=DecisionType.UNKNOWN.value)
    proposed_settlement_amount: Mapped[float | None] = mapped_column(Float, nullable=True)

    straight_through: Mapped[bool] = mapped_column(default=False)
    exception_reason: Mapped[str] = mapped_column(String, default="")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    decisions: Mapped[list["ClaimDecision"]] = relationship(back_populates="claim")
    audit_logs: Mapped[list["AuditLog"]] = relationship(back_populates="claim")
    communications: Mapped[list["CommunicationDraft"]] = relationship(back_populates="claim")


class ClaimDecision(Base):
    __tablename__ = "claim_decisions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_id)
    claim_id: Mapped[str] = mapped_column(ForeignKey("claims.id"), nullable=False)
    decision_type: Mapped[str] = mapped_column(String, nullable=False)  # approve/reject/investigate
    amount: Mapped[float | None] = mapped_column(Float, nullable=True)

    idempotency_key: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String, default=DecisionStatus.PROPOSED.value)

    requested_by: Mapped[str] = mapped_column(String, default="settlement_agent")
    approved_by: Mapped[str | None] = mapped_column(String, nullable=True)
    rejection_reason: Mapped[str] = mapped_column(String, default="")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    claim: Mapped["Claim"] = relationship(back_populates="decisions")


class CommunicationDraft(Base):
    __tablename__ = "communication_drafts"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_id)
    claim_id: Mapped[str] = mapped_column(ForeignKey("claims.id"), nullable=False)
    draft_text: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String, default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    claim: Mapped["Claim"] = relationship(back_populates="communications")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=gen_id)
    claim_id: Mapped[str | None] = mapped_column(ForeignKey("claims.id"), nullable=True)
    actor: Mapped[str] = mapped_column(String, nullable=False)
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    event_data: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    prev_hash: Mapped[str] = mapped_column(String, default="")
    record_hash: Mapped[str] = mapped_column(String, default="")

    claim: Mapped["Claim"] = relationship(back_populates="audit_logs")
