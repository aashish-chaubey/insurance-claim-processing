# Project 4 — Intelligent Insurance Claims Processing

Insurance capstone from the Enterprise-Grade Agentic AI Project Catalogue. Automates inbound claim
processing (health, auto, property) — coverage validation, fraud screening, settlement calculation
and customer communication — with human review, audit trail and guardrails.

## Agent team

Claim Intake → Document → Coverage → Fraud → Settlement → Communication

- **Claim Intake**: records the inbound claim and starts the audit trail.
- **Document** (LLM): classifies claim type and extracts claimant, policy, incident, invoice and
  itemised-bill fields in one call; also identifies missing supporting documents.
- **Coverage** (SQL retrieval + LLM): looks up the claimant and policy by exact identifiers in
  PostgreSQL, gives the retrieved policy facts to an LLM, and receives a structured coverage
  assessment. This is a simple SQL-grounded RAG pattern; it needs no vector database because policy
  records are already structured. The model cannot mark a claim covered if the database did not
  verify the claimant, policy, and their match, or if any required assessment check fails.
- **Fraud** (database context + LLM): gives the model extracted claim facts, prompt-injection scan
  results, and a compact history of earlier claims on the same policy. The LLM returns a risk score,
  named signals, and an explanation; the score is bounded to 0–1. Raw narrative and attachment text
  are scanned locally but are not sent in this additional LLM request.
- **Settlement** (deterministic): recommends approve/reject/investigate, calculates the proposed
  settlement (`invoice − deductible`, capped at remaining coverage), and proposes a decision with an
  idempotency key; never auto-executes a decision that needs human sign-off.
- **Communication** (LLM): drafts the claimant-facing message, only ever using masked identifiers.

## Stack

Python 3.11.6, FastAPI, SQLAlchemy 2.0, PostgreSQL (Docker Compose by default), OpenAI structured
outputs (`gpt-4o-mini` by default), server-rendered reviewer dashboard (Jinja2), pytest. A
successful claim runs four LLM stages (document extraction, coverage assessment, fraud triage, and
communication drafting); the deterministic intake, settlement math, and safety guardrails remain
application code.

## Quickstart

Follow the section for your operating system from the project root (the folder containing this
README). You need **Python 3.11.6**, **Docker Desktop** with its engine running, and an API key for
OpenAI or an Azure OpenAI deployment in Microsoft Foundry. Docker runs the PostgreSQL database;
Python packages are installed with `pip`.

### 1. Configure `.env`

In VS Code, create a file named `.env` next to this README. Do not name it `.env.txt`, commit it, or
share its keys. Use **one** of these configurations and include the database URL:

For OpenAI:

```dotenv
LLM_PROVIDER=openai
OPENAI_API_KEY=your-openai-key
LLM_MODEL=gpt-4o-mini
DATABASE_URL=postgresql+psycopg://claims_app:claims_app_pw@localhost:5434/insurance_claims
ENV=local
```

For Microsoft Foundry / Azure OpenAI:

```dotenv
LLM_PROVIDER=azure_openai
AZURE_OPENAI_API_KEY=your-azure-openai-key
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_API_VERSION=2024-10-21
AZURE_OPENAI_DEPLOYMENT=your-deployment-name
DATABASE_URL=postgresql+psycopg://claims_app:claims_app_pw@localhost:5434/insurance_claims
ENV=local
```

In Foundry, use the Azure OpenAI endpoint and key for your model deployment. The deployment name is
the name assigned to the deployment, which may differ from the model name. Never paste real keys
into source code, issues, or chat.

### 2. Create the Python environment and install dependencies

The version check must print **Python 3.11.6**. If it does not, install/select Python 3.11.6 before
continuing.

**Windows (PowerShell):**

```powershell
py -3.11 --version
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe --version
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

**macOS (Terminal):**

```bash
python3.11 --version
python3.11 -m venv .venv
.venv/bin/python --version
.venv/bin/python -m pip install -r requirements.txt
```

If the version printed from the new `.venv` is not 3.11.6, stop and recreate it using the Python
3.11.6 interpreter.

### 3. Start the database and initialize the demo data

Run these commands from the project root. Docker Desktop must be running first.

**Windows (PowerShell):**

```powershell
docker compose up -d postgres
docker compose ps
.\.venv\Scripts\python.exe scripts\init_db.py
.\.venv\Scripts\python.exe scripts\generate_synthetic_data.py
```

**macOS (Terminal):**

```bash
docker compose up -d postgres
docker compose ps
.venv/bin/python scripts/init_db.py
.venv/bin/python scripts/generate_synthetic_data.py
```

Wait until `docker compose ps` shows PostgreSQL as **healthy**. The generator seeds sample claimant
and policy records and writes 200 synthetic claims to `data/generated/claims.jsonl`. Generating
these claims does not yet put them on the dashboard.

### 4. Process sample claims (live LLM calls)

This step sends synthetic claim text to your configured model and may incur API charges. Run a small
batch to start:

**Windows (PowerShell):**

```powershell
.\.venv\Scripts\python.exe scripts\run_pipeline.py --limit 5
```

**macOS (Terminal):**

```bash
.venv/bin/python scripts/run_pipeline.py --limit 5
```

The batch summary should show processed claims, not all claims in `exception`. The script adds new
claims each time it runs; use `--limit 5` for a demo rather than repeatedly running the full batch.

### 5. Start the dashboard

Keep the server running in this terminal. Open `http://localhost:8001/` for the dashboard or
`http://localhost:8001/review` for the reviewer queue.

**Windows (PowerShell):**

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8001
```

**macOS (Terminal):**

```bash
.venv/bin/python -m uvicorn app.main:app --reload --port 8001
```

To stop the server, press **Ctrl+C**. To stop the database when you are finished, run
`docker compose down` from the project root. Your database data is retained for the next run.

### Run tests (no API calls)

**Windows (PowerShell):**

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

**macOS (Terminal):**

```bash
.venv/bin/python -m pytest -q
```

Tests use an in-memory SQLite database and mocked LLM calls; no running PostgreSQL server or API
credits are needed for the test suite.

For additional setup details and troubleshooting, see [HOW_TO_RUN.md](./HOW_TO_RUN.md).

### Microsoft Foundry / Azure OpenAI

Select an Azure OpenAI model deployment in Foundry and set its endpoint, key, and deployment name
in `.env` (do not commit the file):

```dotenv
LLM_PROVIDER=azure_openai
AZURE_OPENAI_API_KEY=your-key
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_API_VERSION=2024-10-21
AZURE_OPENAI_DEPLOYMENT=your-deployment-name
```

`AZURE_OPENAI_DEPLOYMENT` is the deployment name from Foundry, not necessarily the underlying model
name. Restart the application after changing `.env`. The existing `OPENAI_API_KEY` configuration
continues to work when `LLM_PROVIDER=openai`.

## Guardrails implemented

- Policy numbers and national IDs are masked everywhere except the underlying DB row
  (`app/security.py:mask_identifier`).
- `reject` and `investigate` **always** require human review — never straight-through, since a
  rejection is an adverse action against the claimant and an investigation IS the human-review path.
- `approve` is only straight-through eligible above the confidence threshold, below the fraud-score
  threshold, and under the auto-approve amount ceiling (`app/config.py`).
- Every settlement decision carries a deterministic idempotency key derived from
  `(claim_id, decision_type)` — re-running the pipeline on the same claim never double-books a decision.
- `execute_decision` is idempotent and its effect on the policy (`claimed_amount_ytd`) is **additive**,
  never an overwrite — safe when multiple unrelated claims settle against the same policy (several
  claimants in the synthetic dataset hold policies hit by more than one claim).
- Untrusted claim narrative/document content is wrapped before LLM calls and scanned locally for
  prompt-injection markers; the fraud agent receives the scan results as evidence for its assessment.
- The audit log is hash-chained (`app/audit.py`, `GET /audit/verify_chain`) so tampering is detectable.

## A note on review terminology

`POST /decisions/{id}/review` takes `decision: "approve" | "reject"` meaning *the reviewer's verdict
on the Settlement Agent's proposal* — not the claim outcome directly. Since a proposal can itself be
`reject` or `investigate`, "the reviewer approves a reject-type decision" means *confirming the claim
should be rejected* (claim ends up `executed`, i.e. the confirmed rejection was carried out), while
"the reviewer rejects" any proposal means *declining it* (claim ends up `status=rejected`, i.e. the
proposed action was not carried out). This mirrors Project 1's maker-checker semantics exactly. It
reads a little oddly for `reject`-type proposals specifically; a production version would likely
rename the review field to `concur`/`override` to remove the ambiguity.

## Data

`scripts/generate_synthetic_data.py` produces 200 **synthetic, non-real** claims — no real
claimant, policy or medical/incident data is used anywhere in this project. ~10% reference a
non-existent policy number, ~10% hit a policy exclusion, ~10% violate the waiting period, ~15% omit
standard supporting documents, ~8% are deliberately vague, ~4% embed a prompt-injection attempt, and
~6% of policies are lapsed — so the guardrails and exception paths are genuinely exercised by the
batch run, not just the happy path. Settlement amounts are triangular-distributed (skewed toward
small/routine claims, like real claims data) so the auto-approve ceiling is meaningfully exercised.

## What's stubbed vs. real for this local build

Real: FastAPI service, PostgreSQL schema, all 6 agents (4 LLM-backed analysis/drafting stages plus
deterministic intake and settlement guardrails), maker-checker review
workflow, idempotency, hash-chained audit log, prompt-injection screening, reviewer dashboard, pytest
suite.

Stubbed (would be real enterprise integrations in production): OCR (bills/photos arrive as
pre-extracted text), policy administration system (coverage checks run against a local `policies`
table instead of a real policy admin platform), payment gateway (settlement "execution" increments a
local `claimed_amount_ytd` instead of triggering a real payout), claim intake channels (claims are
loaded from a generated file / API call instead of live email/portal/API), customer communication
channels (drafts are stored, not actually sent), RBAC/SSO (the `decided_by` field is free text
instead of an authenticated reviewer identity), CI/CD and Kubernetes deployment.
