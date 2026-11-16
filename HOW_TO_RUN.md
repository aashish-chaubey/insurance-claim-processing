# How to Run — Project 2: Intelligent Insurance Claims Processing

Complete, copy-pasteable instructions to run this project: environment setup → database → synthetic
data → web dashboard → shutdown. The default local setup uses PostgreSQL in Docker Compose.

Use Python **3.11.6** and `pip` only. Docker Compose runs PostgreSQL 16 on port **5434**. A separate
Homebrew PostgreSQL 14 option is available if you prefer not to use Docker.

---

## 0. Prerequisites

| Requirement | Notes |
|---|---|
| Python 3.11.6 | Use the same version for the virtual environment |
| `pip` | Invoked through the virtual environment's Python |
| Docker Compose | Recommended PostgreSQL setup; alternatively, use Homebrew PostgreSQL 14 |
| An OpenAI or Azure OpenAI API key | Required for live Document/Communication agent calls |

---

## 1. Set your API key

```bash
cd "02-insurance-claim-processing"
```

`.env` should contain your database settings and one of the LLM configurations below. Never commit
this file or paste API keys into chat.

Make sure `DATABASE_URL` targets port **5434** when using Docker Compose. The database credentials
must match the values in `docker-compose.yml`.

```bash
cat > .env <<'EOF'
OPENAI_API_KEY=sk-...your-key-here...
LLM_MODEL=gpt-4o-mini
DATABASE_URL=postgresql+psycopg://claims_app:claims_app_pw@localhost:5434/insurance_claims
ENV=local
EOF
```

### Microsoft Foundry / Azure OpenAI

In Foundry, use an Azure OpenAI model deployment and add its Azure OpenAI endpoint, key, and
deployment name to `.env`:

```dotenv
LLM_PROVIDER=azure_openai
AZURE_OPENAI_API_KEY=your-azure-openai-key
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_API_VERSION=2024-10-21
AZURE_OPENAI_DEPLOYMENT=your-deployment-name
```

The deployment name is the name assigned to the model deployment in Foundry. Keep the key private.
The app's default API version is `2024-10-21`; set `AZURE_OPENAI_API_VERSION` if your Azure resource
requires another supported version. Restart the app after editing `.env`.

---

## 2. Install dependencies

```bash
python3 --version  # Must print Python 3.11.6
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

---

## 3. Start PostgreSQL

### Docker Compose (recommended)

```bash
docker compose up -d postgres
docker compose ps
```

The Compose service runs PostgreSQL 16 and exposes port **5434** on the host. It creates the
`insurance_claims` database and `claims_app` role automatically.

### Homebrew PostgreSQL 14 (alternative)

The helper script requires PostgreSQL 14 binaries at
`/opt/homebrew/opt/postgresql@14/bin`. Use Docker Compose above if that version is not installed.

```bash
scripts/local_postgres.sh start
/opt/homebrew/opt/postgresql@14/bin/psql -h localhost -p 5434 -U claims_app -d postgres \
  -c "ALTER USER claims_app WITH PASSWORD 'claims_app_pw';" \
  -c "CREATE DATABASE insurance_claims OWNER claims_app;"
```

---

## 4. Create the database tables

```bash
.venv/bin/python scripts/init_db.py
```

Expected: `Tables created.`

---

## 5. Seed the policy database

```bash
.venv/bin/python scripts/generate_synthetic_data.py
```

Seeds ~70 claimants with ~84 policies (health/auto/property — some claimants hold more than one
policy, and some policies get hit by more than one claim, to exercise additive
`claimed_amount_ytd` behavior). It also writes a legacy synthetic claims file; the main batch
pipeline does not use it.

Expected output:
```
Seeded 70 claimants and 84 policies.
Wrote 200 synthetic claims to .../data/generated/claims.jsonl
```

---

## 6. Extract PDFs with Azure Document Intelligence

Configure `AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT` and `AZURE_DOCUMENT_INTELLIGENCE_KEY` in `.env`,
then follow the platform-specific commands in
[README.md](README.md#extract-raw-pdfs-with-azure-document-intelligence). The extracted JSON
files are written to `data/extracted`.

## 7. Optional: smoke-test the live pipeline (makes real API calls)

```bash
.venv/bin/python -m scripts.run_pipeline --limit 5
```

The pipeline reads Azure extraction JSON by default from `data/extracted`. Each document may make
four LLM calls (Document, Coverage, Fraud, Communication), so start with a small batch and consider
your provider's pricing. Confirm this works — a mix of `approve`/`reject`/`investigate` decisions,
no `FAILED` lines — before running the full batch.

---

## 8. Optional: run the full extracted-document batch (live LLM)

```bash
.venv/bin/python -m scripts.run_pipeline
```

Runs sequentially over extracted JSON files and can take substantially longer now that each document
makes up to four LLM calls; time and cost depend on the selected model and provider. Safe to
interrupt, but rerunning inserts new claim rows rather than resuming the previous batch. Settlement
decisions are idempotent per `(claim_id, decision_type)` when an existing claim is explicitly rerun
through the API.

Watch progress from another terminal:

```bash
tail -f pipeline_run.log   # if you redirected output, e.g. `... > pipeline_run.log 2>&1 &`

# or check progress directly in the Docker database:
docker compose exec -T postgres psql -U claims_app -d insurance_claims \
  -c "SELECT count(*) AS total, count(*) FILTER (WHERE status='exception') AS exceptions FROM claims;"
```

---

## 8. Start the web app (API + reviewer dashboard)

```bash
.venv/bin/python -m uvicorn app.main:app --reload --port 8001
```

(Port 8001, not 8000 — Project 1 uses 8000; both can run simultaneously.)

| URL | What it is |
|---|---|
| http://localhost:8001/ | Claim list — type, status, fraud score, decision, amount, straight-through flag |
| http://localhost:8001/review | Claims review queue — approve/reject pending decisions |
| http://localhost:8001/claims/{id}/view | Full claim detail: narrative, extracted data, coverage/fraud notes, decision(s), communication draft |
| http://localhost:8001/docs | Interactive OpenAPI docs |
| http://localhost:8001/audit?claim_id=... | Raw audit trail for a claim (JSON) |
| http://localhost:8001/audit/verify_chain | Confirms the hash-chained audit log hasn't been tampered with |

---

## 9. Shut everything down

```bash
# stop the web server: Ctrl+C in its terminal
docker compose down                 # if you used Docker Compose
scripts/local_postgres.sh stop      # if you used the Homebrew PostgreSQL 14 path
```

---

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| `psql: could not connect to server` | Postgres isn't running — start it with `docker compose up -d postgres` |
| `Address already in use` on `pg_ctl start` | Something else already owns port 5434 — check you're not confusing this with Project 1's 5433 instance |
| `scripts/local_postgres.sh: ... No such file or directory` | Homebrew PostgreSQL 14 is not installed; use Docker Compose or install PostgreSQL 14 |
| `openai.AuthenticationError` | `OPENAI_API_KEY` in `.env` is missing/invalid |
| Azure OpenAI returns `unsupported_value` for `temperature` | Azure requests omit temperature and use the deployment's supported default. Restart the app after updating code. |
| Almost every claim shows non-empty `missing_documents` | Check that `data/extracted` contains Azure Document Intelligence JSON results and their `content.content` includes the document text. |
| Almost no claim is `straight_through` | Check `settlement_auto_approve_max` in `app/config.py` against the settlement amounts you're actually generating — if invoice amounts are much larger than the ceiling, straight-through will rarely trigger by design (that's the guardrail working, not a bug) |
| A claim's `status` is `exception` | Open it at `/claims/{id}/view`, read `exception_reason`; check `/audit?claim_id=...` for the failing stage; fix root cause; `POST /claims/{id}/rerun` (safe — idempotent) |

Full architecture notes: `docs/architecture.md`. Operational runbook: `docs/runbook.md`. Project
scope, guardrails and what's stubbed vs. real: `README.md`.
