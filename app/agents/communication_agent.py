from app.agents.llm_client import structured_call

SYSTEM_PROMPT = """You are the Communication Agent in an insurer's claims automation pipeline. Draft a \
clear, empathetic, professional message to the claimant about their claim's status.

Rules:
- Never include a full policy number or national ID. Only ever use the masked forms given to you.
- Do not invent facts, coverage details, or amounts. Only reference the claim number, decision, status \
and settlement amount (if any) given to you.
- If the claim is pending investigation or additional documents are needed, say so clearly and list \
what's needed if given.
- Keep it concise and appropriate for a customer-facing claims communication."""

JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "subject": {"type": "string"},
        "body": {"type": "string"},
    },
    "required": ["subject", "body"],
    "additionalProperties": False,
}


def draft_communication(
    *,
    claim_number: str,
    claimant_name: str,
    decision_type: str,
    outcome_status: str,
    masked_policy_number: str,
    settlement_amount: float | None,
    missing_documents: list,
    notes: str,
) -> dict:
    user_prompt = (
        f"Claim number: {claim_number}\n"
        f"Claimant: {claimant_name}\n"
        f"Decision: {decision_type}\n"
        f"Outcome status: {outcome_status}\n"
        f"Masked policy number: {masked_policy_number}\n"
        f"Settlement amount: {settlement_amount if settlement_amount is not None else 'N/A'}\n"
        f"Missing documents (if any): {missing_documents}\n"
        f"Additional notes: {notes}"
    )
    return structured_call(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_prompt,
        schema_name="communication_draft",
        json_schema=JSON_SCHEMA,
    )
