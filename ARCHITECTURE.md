# Architecture — VQG (Visual Quiz Generator)

> Update this when you make a technical decision that isn't obvious from the stack.
> Rules here override Claude's defaults for this codebase.

---

## Overview

VQG is a backend-heavy pipeline tool. A PDF goes in, an Anki `.apkg` comes out. The FastAPI backend accepts uploads and serves status/download endpoints. All heavy processing (PDF parsing, Gemini API calls, quiz generation) runs inside a Celery worker so the API stays non-blocking. SQLite tracks job state. The frontend is a minimal Next.js app: upload form, progress poller, download button, and an in-browser card preview.

The pipeline is a sequential, step-based process: **parse → triage → process → generate → export**. Each step is a pure function in `backend/pipeline/`. The Celery worker in `backend/workers/celery_app.py` is the only place that calls these functions in sequence.

---

## Stack

| Layer | Choice | Why this, not the obvious alternative |
|-------|--------|---------------------------------------|
| Backend | FastAPI (Python) | Async-native, fast to iterate, matches Gemini SDK (Python-first) |
| Task queue | Celery + Redis | Gemini calls take 5–30s per image — can't block HTTP. Celery tasks survive server restarts. |
| PDF parsing | PyMuPDF (`fitz`) | Renders any page at arbitrary DPI. Works for raster, vector, and mixed PDFs. No ML models, zero memory issues. |
| Region detection | Gemini Vision (via bbox prompt) | Asks Gemini where diagrams are on each page — returns normalized bounding boxes. Replaces all heuristic PDF-type detection. |
| Vision + text AI | Gemini 3 Flash Preview (`gemini-3-flash-preview`) | Replaces gemini-2.5-flash (deprecated June 17 2026). Used for triage, label extraction, region detection, and quiz generation. |
| Image editing | PIL (Pillow) | Numbered overlay: white erase rectangle over original label text, yellow circle badge with number on top. Deterministic, always succeeds. |
| Gemini SDK | `google-genai` (not `google-generativeai`) | `google-generativeai` support ended Nov 30 2025. New SDK: `from google import genai`, `genai.Client(api_key=...)` |
| Anki export | genanki 0.13.0 | Produces valid .apkg with embedded media. Standard library for this. |
| Storage | Local filesystem (MVP) | Zero cost, zero setup. Storage path configurable via .env for future migration. |
| Database | SQLite | Zero setup for MVP. Job tracking only — no relational complexity. |
| Frontend | Next.js (React) | Upload form, progress poller, download button, in-browser card preview. |

---

## Directory structure

```
vqg/
├── backend/
│   ├── main.py                          # FastAPI app — mounts routes, inits DB
│   ├── config.py                        # All env vars loaded here. Everything imports from config.
│   ├── routes/
│   │   ├── upload.py                    # POST /upload — save PDF, create job, enqueue task
│   │   ├── jobs.py                      # GET /jobs/{id} — read job status from SQLite
│   │   ├── export.py                    # GET /export/{id}/anki — serve .apkg file
│   │   └── preview.py                   # GET /jobs/{id}/preview — card preview data + image serving
│   ├── pipeline/                        # Pure functions. No orchestration logic here.
│   │   ├── pdf_parser.py               # PyMuPDF → render pages → Gemini bbox detection → cropped regions
│   │   ├── image_triage.py             # Gemini Vision → route (LABEL_BLANK | SEQUENCE_ORDER | CONTEXT_MCQ | ...)
│   │   ├── label_extractor.py          # Gemini Vision → labels with x,y coordinates
│   │   ├── quiz_generator.py           # Gemini Flash → MCQ questions for LABEL_BLANK images
│   │   ├── context_mcq_generator.py    # Gemini Vision → factual MCQs from text slides / clinical photos
│   │   ├── process_diagram_generator.py # Gemini Vision → step/mechanism MCQs from process diagrams
│   │   └── anki_exporter.py            # genanki → .apkg path (handles all 3 card types)
│   ├── workers/
│   │   └── celery_app.py               # THE orchestrator. Calls pipeline steps in order. Updates job status.
│   ├── models/
│   │   ├── schemas.py                   # Pydantic models for all inter-step data structures
│   │   └── db.py                        # SQLite helpers: init_db, create_job, update_job, get_job
│   └── utils/
│       ├── gemini_client.py             # genai.Client, rate limiter, JSON fence-stripping, retry logic
│       └── image_utils.py               # PIL helpers: draw_numbered_overlay, compute_ssim (unused but kept)
├── frontend/
│   ├── pages/
│   │   ├── index.js                     # Upload form + drag-drop
│   │   └── results/[jobId].js           # Status poller + download button + card preview
│   └── components/
│       └── ProgressTracker.js           # Stage stepper + image progress bar
├── storage/                             # Runtime only — not committed
│   ├── uploads/                         # Incoming PDFs (keyed by job_id)
│   ├── images/                          # Extracted region crops per job: storage/images/{job_id}/
│   ├── processed/                       # Numbered overlay images: storage/processed/{job_id}/
│   └── exports/                         # Final .apkg files: storage/exports/{job_id}/
├── requirements.txt
├── .env
└── docker-compose.yml                   # Redis only
```

**Kept on disk but not imported by active pipeline:**
- `backend/pipeline/inpainter.py` — Nano Banana 2 inpainting (replaced by numbered overlay)
- `backend/pipeline/quality_checker.py` — SSIM gate + numbered box fallback (replaced by deterministic overlay)

---

## Data flow

The happy path for a single PDF through the pipeline:

1. **Upload** — `POST /upload` → PDF saved to `storage/uploads/`, job created in SQLite, Celery task enqueued
2. **PARSING** — `parse_pdf()` → for each page: render at 2× DPI → Gemini detects diagram bounding boxes → crop each region → save to `storage/images/{job_id}/page{N}_region{M}.png`
3. **TRIAGING** — for each crop: `triage_image()` → route to one of: `LABEL_BLANK | SEQUENCE_ORDER | CONTEXT_MCQ | SKIP`
4. **PROCESSING** — by route:
   - `LABEL_BLANK` → `extract_labels()` → `draw_numbered_overlay()` → save `{stem}_numbered.png` to `storage/processed/{job_id}/`
   - `SEQUENCE_ORDER` → passthrough (original image used)
   - `CONTEXT_MCQ` → passthrough (original image used, or no image for text-only cards)
5. **GENERATING** — by route:
   - `LABEL_BLANK` → `generate_quiz()` with `target_label_ids` (exact numbered labels) → "What is structure #N?" questions
   - `SEQUENCE_ORDER` → `generate_process_diagram_quiz()` → step/mechanism/order questions
   - `CONTEXT_MCQ` → `generate_context_mcq()` → standalone factual MCQs (no slide references)
6. **EXPORTING** — `build_anki_deck()` → `.apkg` saved to `storage/exports/{job_id}/`
7. Job status updated to `COMPLETE` with `export_path`
8. Frontend polls `GET /jobs/{id}` until COMPLETE → shows download button + fetches card preview
9. User views cards in browser or downloads `.apkg` for Anki

**Rule:** FastAPI routes never call pipeline functions. They only write to storage, create jobs, and enqueue Celery tasks.

---

## Three image types

| Route | What it is | Processing | Quiz format |
|-------|-----------|------------|-------------|
| `LABEL_BLANK` | Anatomical diagram / radiograph with callout labels | Numbered overlay drawn on original | "What is structure #N?" × N questions — one per badge |
| `SEQUENCE_ORDER` | Process diagram / flowchart / mechanism (e.g. DNA replication, proofreading steps) | Original image unchanged | Step identification, mechanism, and sequence order questions |
| `CONTEXT_MCQ` | Text slide, clinical positioning photo, technique diagram without callout labels | Original image unchanged (or no image for pure text) | Standalone factual MCQ — no slide references allowed |

---

## Module boundaries

- `pipeline/` modules are pure functions — they do not import from `routes/` or `workers/`
- `workers/celery_app.py` imports from `pipeline/` — it is the only orchestrator
- `routes/` imports from `models/db.py` and queues Celery tasks — nothing else
- `utils/gemini_client.py` is imported by pipeline modules — it is the only place `google.genai` is called
- `models/schemas.py` is imported everywhere — no circular deps (it imports nothing from the project)
- `config.py` is imported everywhere for env vars — never use `os.getenv` outside of `config.py`

---

## Key decisions

### Universal page renderer (replacing heuristic PDF detection)
**Decision:** Render every PDF page at `PAGE_RENDER_SCALE` (default 2×) and ask Gemini Vision to return bounding boxes for all quiz-worthy diagram regions.
**Why:** The previous approach used `_is_slide_page()` (aspect ratio heuristics) + a separate `panel_splitter.py` module that only handled left-right splits. This broke on textbook PDFs (vector graphics, 1×1px raster placeholders) and any non-horizontal panel layout. Gemini handles all cases in one prompt: full-page slides, textbook figures, side-by-side panels, stacked diagrams.
**Consequences:** Parsing now makes one Gemini API call per page. Text-only pages return `[]` and are skipped. Fallback: if Gemini fails, the full rendered page is saved as a single region (never silently drops a page).

### Numbered overlay instead of inpainting
**Decision:** Keep original callout arrows, draw yellow numbered circle badges where the text labels were. One numbered image shared across all questions for that diagram.
**Why:** Nano Banana 2 inpainting was fragile — SSIM failures, reduced output resolution, expensive API calls, probabilistic quality. Numbered overlay is deterministic (PIL), always succeeds, and matches how anatomy atlases (Netter, Gray's) work. Students see "What is structure #6?" with a numbered diagram.
**Consequences:** `inpainter.py` and `quality_checker.py` kept on disk but not imported. SSIM check removed from active pipeline.

### Question-badge alignment via `_numbered_label_ids`
**Decision:** Celery stores the ordered list of label IDs that received badges (`_numbered_label_ids`) in the result dict, then passes it to `generate_quiz()` as `target_label_ids`.
**Why:** Without this, `generate_quiz()` would filter to `suggested_quiz_labels` (Gemini's top 3–6 picks) and cap at 6 — producing fewer questions than numbered badges on the image. With `target_label_ids`, question count = badge count, and `#N` in the question text always matches badge N.

### CONTEXT_MCQ cards are image-free
**Decision:** CONTEXT_MCQ question cards show no image — question text only on the card front.
**Why:** If the slide/photo is shown, the student can just read the answer off it. Questions must be answerable from memory. The `context_mcq_generator.py` prompt explicitly bans "according to the slide / based on this image" phrasing.
**Consequences:** `anki_exporter.py` detects `method == "context_mcq"` and sets `image_tag = ""`. Preview endpoint omits `original_image_url` for these items.

### SQLite for MVP
**Decision:** Use raw SQLite with helper functions in `models/db.py`, not SQLAlchemy ORM.
**Why:** Job table is simple (one table, ~11 columns). ORM adds setup complexity with no benefit at this scale.
**Consequences:** No migrations framework. Schema changes are manual.

### Celery for async processing
**Decision:** All pipeline work runs in a Celery worker, not FastAPI background tasks.
**Why:** FastAPI `BackgroundTasks` are tied to the request lifecycle. Celery tasks survive restarts and are properly queued.
**Consequences:** Redis must be running (`docker-compose up -d`). On Windows, Celery worker requires `--pool=solo`.

---

## Integration points

| Service | Purpose | Auth | Notes |
|---------|---------|------|-------|
| Gemini Developer API | Region detection, triage, label extraction, quiz gen (all 3 types) | `GEMINI_API_KEY` in .env | All calls via `gemini_client.py`. `gemini-3-flash-preview` for all vision+text tasks. |

---

## Storage schema

**SQLite table: `jobs`**
```
job_id TEXT PRIMARY KEY
status TEXT                   -- QUEUED | PARSING | TRIAGING | PROCESSING | GENERATING | EXPORTING | COMPLETE | FAILED
pdf_filename TEXT
total_images INTEGER
processed_images INTEGER
skipped_images INTEGER
quiz_count INTEGER
export_path TEXT              -- null until COMPLETE
error TEXT                    -- null unless FAILED
created_at TEXT               -- ISO string
updated_at TEXT               -- ISO string
```

**Filesystem layout:**
```
storage/uploads/{job_id}_{original_filename}.pdf
storage/images/{job_id}/page003_region1.png      -- cropped diagram region from pdf_parser
storage/processed/{job_id}/page003_region1_numbered.png  -- numbered overlay (LABEL_BLANK only)
storage/processed/{job_id}/processing_results.json       -- full pipeline output per job
storage/exports/{job_id}/vqg_export.apkg
```

---

## Performance considerations

- Gemini calls are the bottleneck — one per page for region detection during parsing, plus one per image for triage, label extraction, and quiz generation
- Rate limiter in `gemini_client.py` caps at 80 RPM (Tier 1 is ~150 RPM — buffer for bursts)
- Process one image at a time in the Celery worker loop — do not load all into memory simultaneously
- `PAGE_RENDER_SCALE = 2` chosen as the minimum for Gemini to read labels reliably. Raise to 3 for very dense diagrams with small text.

---

## Security / privacy rules

- Never log image content, PDF text, or extracted labels to console or DB
- API key only in `.env`, loaded via `config.py`
- `storage/` directory not served as a static route — only accessible via `/export/{id}/anki` and `/preview/image/{job_id}/{folder}/{filename}` (path traversal protected: only `images` and `processed` folders allowed, no `..` in any segment)

---

## Known constraints and gotchas

- Gemini bbox coordinates occasionally slightly out of bounds — always clamp: `x0=max(0,...), x1=min(w,...)` before cropping
- Gemini responses that should be JSON often come wrapped in ` ```json ``` ` markdown fences — always strip before parsing (handled in `gemini_client.py`)
- genanki `Package.media_files` must contain **absolute** file paths — relative paths cause missing images in Anki
- Celery worker on Windows requires `--pool=solo` flag
- `google.genai` SDK (not `google.generativeai`) — import pattern: `from google import genai; client = genai.Client(api_key=...)`

---

## What NOT to do

- Do NOT call `google.genai` directly from pipeline modules — use `gemini_client.py`
- Do NOT call pipeline functions from FastAPI routes — only from Celery worker
- Do NOT add heuristic PDF-type detection — Gemini's region detection handles all PDF types universally
- Do NOT use `.then()` chains — all async code uses `async/await`
- Do NOT hardcode model IDs — they come from `config.py` which reads `.env`
- Do NOT write "According to the slide / based on this image" in CONTEXT_MCQ or process diagram questions — questions must be standalone memory tests
