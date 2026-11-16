# Runbook

## Local environment (Docker Compose)

The recommended local database is PostgreSQL 16 from `docker-compose.yml`, exposed on port 5434:

```bash
docker compose up -d postgres
docker compose ps
```

Configure `.env` with a `DATABASE_URL` for the Compose database on port 5434. For OpenAI, set
`OPENAI_API_KEY`. For an Azure OpenAI deployment in Microsoft Foundry, set `LLM_PROVIDER=azure_openai`,
`AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_VERSION`, and
`AZURE_OPENAI_DEPLOYMENT`. See the Foundry example in `README.md`.

`.env` → `DATABASE_URL=postgresql+psycopg://claims_app:claims_app_pw@localhost:5434/insurance_claims`

### Alternative: Homebrew PostgreSQL 14

```bash
scripts/local_postgres.sh start
```

This helper requires PostgreSQL 14 binaries at `/opt/homebrew/opt/postgresql@14/bin`. Use Docker
Compose above if PostgreSQL 14 is not installed.

## First-time setup

```bash
python3 --version  # Must print Python 3.11.6
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt

docker compose up -d postgres
.venv/bin/python scripts/init_db.py
.venv/bin/python scripts/generate_synthetic_data.py
.venv/bin/python -m uvicorn app.main:app --reload --port 8001
```

Each processed claim can make four live LLM calls (Document, Coverage, Fraud, Communication). Run
`.venv/bin/python -m scripts.run_pipeline --limit 10` only when you intend to send
Azure-extracted claim documents to your configured provider; check its pricing first. The default
input is `data/extracted`, which must contain JSON results from Azure Document Intelligence.

## Day-to-day

- Dashboard: http://localhost:8001/
- Review queue: http://localhost:8001/review
- API docs: http://localhost:8001/docs
- Audit chain integrity check: `GET /audit/verify_chain`

## Incident response

- **A claim is stuck in `exception`**: open it in the dashboard, check `exception_reason`, inspect
  `GET /audit?claim_id=...` for the failing stage, fix root cause (e.g. LLM outage, malformed
  content), then `POST /claims/{id}/rerun` — safe to re-run because settlement decisions are
  idempotent per `(claim_id, decision_type)`.
- **Audit chain broken** (`GET /audit/verify_chain` returns `chain_intact: false`): treat as a
  security incident — freeze writes, snapshot the `audit_logs` table, investigate before resuming.
- **A policy's `claimed_amount_ytd` looks wrong**: it should equal the sum of `amount` across every
  `executed` `approve` decision whose claim references that policy — recompute and compare rather
  than trusting the field blindly if you suspect drift.
- **OpenAI API errors during a batch run**: `scripts/run_pipeline.py` logs a `FAILED` line per claim
  and continues; re-run with `--limit` against just the affected claims once resolved.

## Success measures (from the project catalogue)

Tracked via `scripts/run_pipeline.py`'s batch summary and queryable via the API: claim cycle time
(`created_at` → `executed_at` on `claim_decisions`), document completeness accuracy (`missing_documents`
on `extracted_data`), fraud detection precision/recall (would need labeled ground truth — the fraud
score and triggered rules are logged per claim for that evaluation), settlement recommendation
accuracy (`recommended_decision` vs. reviewer's final call), manual touch reduction
(`Claim.straight_through` rate).
