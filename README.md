# MatchMyCancer.ai

**AI-powered oncology report analysis.** Upload or paste a pathology / genomics
report and get, in plain language: the **biomarkers** found, what they **mean**,
matching **FDA-approved therapies** (with a reasoning trail), and matching
**clinical trials** (with AI eligibility summaries).

> ⚕️ **Educational tool only — not medical advice.** It does not diagnose,
> prescribe, or recommend treatment. Every AI claim links back to the source
> text so it can be verified. Always discuss findings with a licensed oncologist.

---

## What it does

```
 Upload / paste report
          │
          ▼
   Text extraction  ──────────────► PDF (PyMuPDF) or OCR (Tesseract) fallback
          │
          ▼
   Clinical extraction (LLM) ─────► biomarkers + diagnosis, with source spans
          │
   ┌──────┼───────────────┬──────────────────┐
   ▼      ▼               ▼                  ▼
 Explain  Therapies      Trials            Guardrails
 (LLM)    (OncoKB/FDA)   (ClinicalTrials)  (source-verify,
          + reasoning    + AI eligibility   confidence)
          trace          summary
          │
          ▼
   Streamed results (SSE) → clean web UI
```

- **Biomarker & diagnosis extraction** — LLM with structured output; every
  finding carries a character span back into the source document.
- **Plain-language explanations** — 8th-grade reading level, per biomarker + an
  overall summary, with mandatory disclaimers.
- **FDA therapy matching** — patient biomarkers → FDA-approved targeted
  therapies (curated OncoKB Level-1 evidence), each with a deterministic
  **reasoning trace** (biomarker → evidence → approval).
- **Clinical-trial matching** — live search against ClinicalTrials.gov v2, ranked
  by biomarker relevance and freshness; the top matches get an AI **eligibility
  summary** (LIKELY / POSSIBLY / UNLIKELY + who qualifies).
- **Hallucination guardrails** — each biomarker is verified against the source
  text; an overall confidence score and warnings are surfaced.
- **Live progress** — results stream stage-by-stage over Server-Sent Events.

## Key design principles

| Principle | How |
|-----------|-----|
| **Zero-PHI / stateless** | Reports are processed **in memory only** — never written to disk, never stored in a database. |
| **Verifiable AI** | Biomarkers carry source character spans; therapies carry reasoning traces; confidence uses honest tiers, not fake 0.00–1.00 scores. |
| **Safe to operate** | `ANALYZE_ENABLED` kill switch, per-route rate limits, and a daily OpenAI **spend ceiling**. |
| **Cheap infra** | No relational DB. ChromaDB holds the public trial index; Redis holds anonymous counters (spend + usage). |

## Tech stack

- **Backend** — FastAPI (async), LangChain + OpenAI (`gpt-4o`), ChromaDB (vector
  index), Redis (counters), PyMuPDF + Tesseract (extraction/OCR), Prometheus
  instrumentation, slowapi (rate limiting).
- **Frontend** — Next.js (App Router) + React + Tailwind CSS, TypeScript.
- **Infra** — Docker (dev + prod multi-stage), GitHub Actions CI. Deploys to
  Vercel (frontend) + Fly.io (backend) + Upstash (Redis) — see [DEPLOY.md](DEPLOY.md).

---

## Quick start (local)

**Backend**
```bash
cd backend
cp ../.env.template .env        # then add your OPENAI_API_KEY
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
# API docs: http://localhost:8000/docs
```

**Redis** (for spend ceiling / usage metrics / readiness)
```bash
docker run -p 6379:6379 redis:7-alpine     # or use docker-compose
```

**Frontend**
```bash
cd frontend
npm install
npm run dev                     # http://localhost:3000
```

Or run the whole stack with Docker:
```bash
docker compose up --build
```

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/upload` | Upload a PDF/image (10 MB max) → extracted text |
| `POST` | `/api/v1/extract` | Text → structured biomarkers + diagnosis |
| `POST` | `/api/v1/analyze` | Full pipeline (synchronous) |
| `POST` | `/api/v1/analyze/stream` | Full pipeline, streamed via SSE |
| `GET`  | `/health` | Liveness check |
| `GET`  | `/api/v1/ready` | Readiness probe (Redis) |
| `GET`  | `/api/v1/health/detailed` | Redis + ChromaDB + key status |
| `GET`  | `/api/v1/stats` | Anonymous usage counters (no PHI) |
| `GET`  | `/api/v1/spend` | Daily OpenAI spend vs ceiling |
| `GET`  | `/api/v1/version` | API version + git commit |
| `GET`  | `/metrics` | Prometheus metrics |

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_API_KEY` | *required* | OpenAI API key |
| `OPENAI_MODEL` | `gpt-4o` | Extraction / explanation model |
| `FRONTEND_ORIGIN` | `http://localhost:3000` | CORS allow-origin |
| `ANALYZE_ENABLED` | `true` | Kill switch for the analysis endpoints |
| `SPEND_CEILING_USD` | `50.0` | Daily OpenAI spend limit |
| `TRIAL_REFRESH_ENABLED` | `false` | Run the daily ClinicalTrials.gov freshness refresh |
| `CHROMA_PERSIST_DIR` | `./chroma_data` | ChromaDB index location |
| `REDIS_HOST` / `REDIS_PORT` | `localhost` / `6379` | Redis (local) |
| `REDIS_URL` | — | Full `rediss://…` URL for managed Redis (Upstash); overrides host/port |

The frontend reads `NEXT_PUBLIC_API_URL` (default `http://localhost:8000`).

## Project structure

```
.
├── backend/
│   └── app/
│       ├── api/v1/        # upload, extract, analyze (+SSE), observability
│       ├── pipelines/     # extraction, explanation, therapy/trial matching,
│       │                  # guardrails, reasoning trace, eligibility summarizer
│       ├── services/      # PDF/OCR, ClinicalTrials.gov client, Chroma indexer
│       ├── core/          # config, logging, startup, metrics
│       ├── models/        # Pydantic domain models
│       └── data/          # curated FDA therapy database
├── frontend/
│   └── src/
│       ├── app/           # pages (main, consent) — Next.js App Router
│       ├── components/    # FileUpload, ResultsDisplay, Icon
│       └── lib/           # API client, consent
├── docker-compose.yml     # local dev stack
├── DEPLOY.md              # Vercel + Fly.io + Upstash deploy guide
└── DECISIONS.md           # architectural decision records
```

## Testing

```bash
cd backend
pytest                    # LLM-backed tests self-skip without OPENAI_API_KEY
```

CI (GitHub Actions) runs the backend tests and a frontend production build on
every push/PR. LLM tests are integration tests — run them locally with a key.

## Data sources

- **ClinicalTrials.gov** (v2 API) — clinical-trial data
- **OncoKB / FDA labels** — curated targeted-therapy evidence
- **OpenAI** — extraction, explanation, and eligibility-assessment models

## License

No license yet — add one before making the repository public if you want to
define reuse terms.

---

*This project is for educational and informational purposes only and is not a
substitute for professional medical advice, diagnosis, or treatment.*
