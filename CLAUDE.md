# VQG (Visual Quiz Generator) — Claude Code Context

> **Session start:** Read PRD.md → ARCHITECTURE.md → last 3 entries of DEVLOG.md
> **Session end:** Update DEVLOG.md before closing — what changed, how it works, files affected, known issues

---

## Project

**What:** Takes a PDF (textbook/notes), extracts images, removes text labels via AI inpainting, and exports an Anki `.apkg` deck where students identify blanked-out structures.
**Who:** Solo build — target users are medical/biology students
**Stack:** Python + FastAPI, Celery + Redis, Next.js frontend, Gemini 2.5 Flash + Gemini 3.1 Flash Image (Nano Banana 2), marker-pdf, genanki, SQLite
**Status:** Planning — scaffolding complete, nothing built yet
**Repo:** N/A

---

## Structure

```
vqg/
├── backend/
│   ├── main.py
│   ├── config.py
│   ├── routes/
│   │   ├── upload.py
│   │   ├── jobs.py
│   │   └── export.py
│   ├── pipeline/
│   │   ├── pdf_parser.py
│   │   ├── image_triage.py
│   │   ├── label_extractor.py
│   │   ├── inpainter.py
│   │   ├── quality_checker.py
│   │   ├── quiz_generator.py
│   │   └── anki_exporter.py
│   ├── workers/
│   │   └── celery_app.py
│   ├── models/
│   │   └── schemas.py
│   └── utils/
│       ├── gemini_client.py
│       └── image_utils.py
├── frontend/
│   ├── pages/
│   │   ├── index.js
│   │   └── results/[jobId].js
│   └── components/
│       └── ProgressTracker.js
├── storage/
│   ├── uploads/
│   ├── images/
│   ├── processed/
│   └── exports/
├── requirements.txt
├── .env
└── docker-compose.yml
```

---

## Commands

```bash
# Start backend dev server
uvicorn backend.main:app --reload

# Start Celery worker
celery -A backend.workers.celery_app worker --loglevel=info

# Start Redis (via Docker)
docker-compose up -d

# Start frontend dev server
cd frontend && npm run dev
```

---

## Patterns — project-specific

- All Gemini API calls go through `backend/utils/gemini_client.py` — never call `google.generativeai` directly from pipeline modules
- All Gemini JSON responses must strip markdown fences before parsing — always use the fence-stripping helper
- SSIM quality check is mandatory after every Nano Banana 2 inpainting call — never skip it
- If inpainting SSIM < 0.60 or > 0.98, fall back to numbered box overlay (never silently fail)
- All SQLite reads/writes go through `backend/models/db.py` helper functions — never raw SQL from pipeline
- Celery worker (`celery_app.py`) is the only orchestrator — FastAPI routes just enqueue jobs and return job_id
- All pipeline steps are pure functions: data in → result out, side effects limited to writing to `storage/`

---

## Model IDs

- Triage + label extraction + quiz gen: `gemini-3-flash-preview` (gemini-2.5-flash deprecated June 17 2026)
- Inpainting (Nano Banana 2): `gemini-3.1-flash-image-preview`
- Same `GEMINI_API_KEY` for both — both on the Gemini Developer API
- SDK: `google-genai` (NOT `google-generativeai` — that package's support ended Nov 30 2025)

---

## Rules — always apply

- Read a file before editing it
- Run build/tests before declaring a task done
- Ask before making changes that touch more than 5 files
- Don't add features, refactoring, or comments beyond what was asked
- If requirements are ambiguous, ask — don't guess
- Never log user content, PDF text, or API keys
- All async FastAPI routes use async/await
- All Gemini calls wrapped in try/except — retry once, then skip image on second failure

---

## Privacy / Security

- No analytics, no external requests beyond Gemini API
- API key lives only in `.env`, never hardcoded
- Never log image content or extracted PDF text

---

## Known issues / active context

- Nothing built yet — Week 1 starts with FastAPI setup + marker-pdf integration
- Verify `gemini-3.1-flash-image-preview` model ID is still live before building inpainter
- marker-pdf pinned at 0.2.17 — newer versions may break `convert_single_pdf` API signature
