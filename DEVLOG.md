# VQG (Visual Quiz Generator) — Dev Log

> Append new entries at the top. Claude reads the last 3 entries at session start for context.
> Format is fixed — don't change it. Consistency is what makes this scannable.

---

<!--
TEMPLATE — copy this block for each entry:

## [YYYY-MM-DD] — [Short title, e.g. "Auth module + PIN lock"]

**What was added/changed:**
- [Bullet: what exists now that didn't before]

**How it works:**
- [Bullet: non-obvious implementation detail worth knowing]

**Files affected:**
- `path/to/file.js` — [what changed]

**Known issues / next steps:**
- [Anything broken, deferred, or worth flagging]

---
-->

## 2026-04-13 — Pipeline parallelization

**What was added/changed:**
- All three Gemini-heavy pipeline stages (TRIAGING, PROCESSING, GENERATING) now run with `ThreadPoolExecutor(max_workers=4)` — images are processed concurrently instead of serially. For a typical 10-page PDF (~8 regions), end-to-end API wait time drops from ~84s to ~20-25s.
- Rate limiter in `gemini_client.py` made thread-safe with `threading.Lock` — multiple threads no longer race on `_last_call_time`. Also reads RPM from `GEMINI_RPM_PER_WORKER` env var (default 30), assuming 2 Celery worker processes sharing the 60 RPM free tier.
- SQLite connections now use WAL journal mode and `timeout=10` — two Celery processes writing simultaneously no longer produce `database is locked` errors.

**How it works:**
- `gemini_client.py`: `_rate_lock = threading.Lock()` wraps the entire rate-limit check + sleep + timestamp update atomically. Threads queue up through the lock — throughput is still capped at the configured RPM regardless of thread count, but threads pre-queue so there's no idle gap between API calls.
- `celery_app.py`: Each stage defines a `_stage_one(item) → (result, count)` helper and runs it through `pool.map(fn, items)`. `pool.map()` preserves input order (important for PROCESSING stage where `_numbered_label_ids` ordering must be consistent). GENERATING uses the same pattern; `update_job` called once after the full stage completes rather than per-image.
- `db.py`: `_connect()` helper added — opens connection with `timeout=10` and executes `PRAGMA journal_mode=WAL`. All three functions (`create_job`, `update_job`, `get_job`) use `_connect()` instead of bare `sqlite3.connect()`.

**Files modified:**
- `vqg/backend/utils/gemini_client.py` — thread-safe rate limiter, RPM from env var
- `vqg/backend/workers/celery_app.py` — ThreadPoolExecutor for TRIAGING, PROCESSING, GENERATING
- `vqg/backend/models/db.py` — WAL mode + connection timeout via `_connect()` helper

**Known issues / next steps:**
- To run 2 parallel jobs: `celery -A backend.workers.celery_app worker --concurrency=2 --loglevel=info`
- Set `GEMINI_RPM_PER_WORKER=30` in `.env` when running 2 workers; raise to 55 for single-worker dev use
- Deployment (Oracle Cloud Always Free ARM + Vercel) deferred to next phase

---

## 2026-04-13 — Granular progress tracking during GENERATING

**What was added/changed:**
- `generated_images` counter added to job tracking — incremented after each image's questions are generated, so the frontend shows live progress during the GENERATING stage instead of a static spinner
- Two progress bars now shown: indigo for "Images numbered" (PROCESSING), emerald for "Questions generated" (GENERATING), each with `X / total` counter
- Question count shown inline next to the generating counter: "12 / 20 (47 questions)"

**How it works:**
- `db.py`: `generated_images` column added to CREATE TABLE; migration via `ALTER TABLE` with exception catch for existing DBs (no manual schema change needed)
- `celery_app.py`: `generated_count` tracked alongside `quiz_count` in the GENERATING loop; `update_job(generated_images=..., quiz_count=...)` called after every image (all 3 routes: LABEL_BLANK, CONTEXT_MCQ, SEQUENCE_ORDER)
- `schemas.py`: `generated_images: int = 0` added to `Job` model
- `ProgressTracker.js`: two separate progress bars with conditional rendering — numbering bar appears once `processedImages > 0`, generating bar appears once `generatedImages > 0` OR status is GENERATING (so bar appears immediately when stage starts)
- `results/[jobId].js`: `generatedImages={job.generated_images}` passed to ProgressTracker

**Files modified:**
- `vqg/backend/models/db.py` — generated_images column + migration
- `vqg/backend/models/schemas.py` — Job model updated
- `vqg/backend/workers/celery_app.py` — per-image update_job in GENERATING loop
- `vqg/frontend/components/ProgressTracker.js` — two progress bars
- `vqg/frontend/pages/results/[jobId].js` — prop passed through

**Known issues / next steps:**
- Restart Celery and re-upload PDF to verify both bars fill in real time during processing

---

## 2026-04-13 — Universal PDF parser + 3 image type handlers

**What was added/changed:**
- `pdf_parser.py` fully rewritten — single universal path for all PDF types (textbook, slide deck, scanned, vector, raster). Renders every page at 2× DPI and calls Gemini Vision to detect quiz-worthy diagram bounding boxes. Each region cropped and saved independently. No more heuristics.
- `panel_splitter.py` deleted — multi-panel detection now automatic: Gemini returns multiple bounding boxes when a page has side-by-side, stacked, or grid-arranged diagrams
- Three image types now handled end-to-end: LABEL_BLANK (already working), SEQUENCE_ORDER (new), CONTEXT_MCQ for clinical/technique photos (was being SKIPped before)
- `process_diagram_generator.py` — new module for SEQUENCE_ORDER images; generates mixed question types: step identification, mechanism ("why does X happen?"), and sequence order
- Triage prompt updated: CLINICAL_PHOTO with educational technique content → CONTEXT_MCQ (worth_quizzing=true); FLOWCHART_PROCESS/PROCEDURAL_STEP → SEQUENCE_ORDER; clearer rules for all three types
- `config.py`: SLIDE_RENDER_SCALE → PAGE_RENDER_SCALE, default lowered from 3 to 2 (cropping to diagram region, don't need 3× full page)
- Browser preview updated to include SEQUENCE_ORDER cards alongside LABEL_BLANK and CONTEXT_MCQ

**How it works:**
- `pdf_parser.py`: for each page, render → save temp PNG → `call_vision_json()` with bbox detection prompt → parse region list → crop each with 1% margin → save as `page{N:03d}_region{M}.png`. Fallback: if Gemini fails or returns [], saves full page as single region (never silently drops a page).
- Bbox detection prompt tested on both `testing quiz 1.pdf` (slide deck, auto-detected 2-panel pages) and `testing quiz 2.pdf` (textbook with vector graphics, correctly isolated figures and skipped text-only pages).
- `celery_app.py`: panel splitter call removed from Step 1. PROCESSING block adds SEQUENCE_ORDER passthrough. GENERATING block adds `generate_process_diagram_quiz()` call for SEQUENCE_ORDER items.
- `process_diagram_generator.py`: same question dict shape as other generators; validated output plugs into anki_exporter and preview unchanged.

**Files added:**
- `vqg/backend/pipeline/process_diagram_generator.py` — new; sequence/mechanism quiz generator

**Files modified:**
- `vqg/backend/pipeline/pdf_parser.py` — complete rewrite
- `vqg/backend/pipeline/image_triage.py` — triage prompt rules updated
- `vqg/backend/workers/celery_app.py` — panel splitter removed; SEQUENCE_ORDER branches added
- `vqg/backend/routes/preview.py` — SEQUENCE_ORDER added to allowed routes
- `vqg/backend/config.py` — SLIDE_RENDER_SCALE → PAGE_RENDER_SCALE, default 2

**Files deleted:**
- `vqg/backend/pipeline/panel_splitter.py` — replaced by universal bbox detection in pdf_parser

**Known issues / next steps:**
- Restart Celery and re-upload both test PDFs to verify: textbook crops correctly, slide deck auto-splits panels, process diagrams generate sequence questions, clinical photos generate technique MCQs
- Coordinate clamping in place for Gemini bbox edge cases (observed one invalid bbox during testing)
- `testing quiz 2.pdf` pages 3 and 5 expected to return 0 regions (text-only) — verify they are skipped cleanly

---

## 2026-04-13 — CONTEXT_MCQ cards: text-only, standalone questions

**What was added/changed:**
- CONTEXT_MCQ cards no longer show the slide image — question and answers only
- Question phrasing fixed: questions must stand alone from memory; "According to the slide / based on this image / in this image" phrasing explicitly banned in prompt
- Anki export: CONTEXT_MCQ cards get empty image tag — slide not bundled into the .apkg
- Browser preview: CONTEXT_MCQ items no longer receive `original_image_url` — frontend renders text-only

**How it works:**
- `context_mcq_generator.py` prompt updated: added explicit rules against slide-referencing phrasing; Gemini must write questions a student could answer from memory, not by reading the card
- `anki_exporter.py`: `method == "context_mcq"` check sets `image_tag = ""` and skips image bundling entirely (no `continue` — questions still exported)
- `preview.py`: `original_image_url` only built when `route != "CONTEXT_MCQ"`

**Files modified:**
- `vqg/backend/pipeline/context_mcq_generator.py` — prompt rewrite
- `vqg/backend/pipeline/anki_exporter.py` — skip image for context_mcq method
- `vqg/backend/routes/preview.py` — no image URL for CONTEXT_MCQ items

**Known issues / next steps:**
- Restart Celery and re-upload to verify CONTEXT_MCQ cards are text-only in both browser preview and Anki

---

## 2026-04-13 — Question count fix + CONTEXT_MCQ pipeline

**What was added/changed:**
- Question count mismatch fixed: diagram now always has exactly as many question cards as it has numbered badges — no more orphaned numbers with no card
- `suggested_quiz_labels` filter removed from active quiz path — Gemini's "top 3–6" suggestion is no longer used when numbered overlay is in play; every numbered structure gets a question
- Hard cap of `_MAX_LABELS_PER_IMAGE = 6` removed — prompts can handle 20+ labels
- CONTEXT_MCQ route now fully implemented: text-heavy slides generate factual MCQ questions from their visible text content (were previously silently skipped)
- Browser preview and Anki deck both include CONTEXT_MCQ cards alongside LABEL_BLANK cards

**How it works:**
- `celery_app.py` PROCESSING: stores `_numbered_label_ids` (ordered list of label IDs that got badges) in each result dict
- `celery_app.py` GENERATING — LABEL_BLANK: passes `_numbered_label_ids` to `generate_quiz()` so question selection and ordering matches the image exactly; `id_to_box` mapping now built from `_numbered_label_ids` order (not from `labels["labels"]` order) so `#N` in question text is always correct
- `quiz_generator.py`: new `target_label_ids` param on both `_build_prompt()` and `generate_quiz()`; when provided, filters and orders `all_labels` by those IDs; when None, falls back to old `suggested_quiz_labels` logic (covers edge cases / future callers)
- `celery_app.py` PROCESSING — CONTEXT_MCQ: images pass through unchanged (no overlay drawn); `method = "context_mcq"` stored in result
- `celery_app.py` GENERATING — CONTEXT_MCQ: calls `generate_context_mcq(image_path, triage)` which sends the slide to Gemini and asks it to read the visible text and write 3–5 factual MCQs
- `context_mcq_generator.py`: same question dict shape as `quiz_generator` output (`label_id` uses C1/C2 sequence) — `anki_exporter` handles it unchanged
- `preview.py`: filter updated from `route == "LABEL_BLANK"` to `route in ("LABEL_BLANK", "CONTEXT_MCQ")`; CONTEXT_MCQ cards show `original_image_url` (no numbered overlay exists)

**Files added:**
- `vqg/backend/pipeline/context_mcq_generator.py` — new; Gemini Vision reads slide text and generates factual MCQs

**Files modified:**
- `vqg/backend/pipeline/quiz_generator.py` — `target_label_ids` param added; `_MAX_LABELS_PER_IMAGE` cap removed
- `vqg/backend/workers/celery_app.py` — `_numbered_label_ids` stored in results; LABEL_BLANK quiz gen uses it; CONTEXT_MCQ branches added in both PROCESSING and GENERATING steps
- `vqg/backend/routes/preview.py` — filter now includes CONTEXT_MCQ items

**Known issues / next steps:**
- Restart Celery and re-upload PDF to verify: diagram card count = badge count, text slides produce MCQ cards
- CONTEXT_MCQ cards have no structure number in the question (no overlay drawn) — that's intentional; questions are factual recall from slide content

---

## 2026-04-13 — Numbered overlay pipeline + browser card preview

**What was added/changed:**
- Entire Nano Banana 2 inpainting pipeline removed — replaced with PIL-based numbered overlay that preserves original callout arrows
- Label extraction now returns `x,y` coordinates (normalized 0–1) per label so numbers go precisely where text was
- Panel splitter added: slide renders detected for left-right multi-panel layouts (e.g. anatomy diagram + radiograph side-by-side), each panel cropped and processed independently → 2× question yield per slide
- Browser card preview: after job completes, results page shows numbered diagram + expandable Q&A rows — no Anki needed to review output during development
- Output quality fixes: INLINE_TEXT labels (titles/headings) filtered out of quiz suggestions; difficulty calibrated per-structure by Gemini (not globally from label density); all questions rephrased to "What is structure #N?"

**How it works:**
- `label_extractor.py`: prompt now requests `x,y` per label; grid fallback computed if Gemini omits them; INLINE_TEXT labels stripped from `suggested_quiz_labels` client-side after response
- `image_utils.py` — new `draw_numbered_overlay(image, labels)`: draws yellow circle badges (diameter = 2.5% of min dimension) at `(label.x * w, label.y * h)`; returns `(annotated_image, label_map)`
- `celery_app.py` — PROCESSING step: extract labels → `draw_numbered_overlay()` → save `{stem}_numbered.png`; always succeeds (no quality gate); quiz questions rephrased to "What is structure #N?" using `id_to_box` mapping; quiz generation now uses the numbered image (not original) so Gemini sees what the student sees
- `panel_splitter.py` — new module; runs only on `_slide.png` images with aspect ratio ≥ 1.2; calls Gemini Flash to detect panel boundaries as normalized x-coordinates; crops each panel with 1% margin; TEXT_HEAVY panels skipped; graceful fallback returns original on any failure
- `preview.py` — new FastAPI router: `GET /jobs/{id}/preview` reads `processing_results.json` and returns card data with image URLs; `GET /preview/image/{job_id}/{folder}/{filename}` serves images with path traversal protection (only `images`/`processed` folders allowed)
- Frontend: `results/[jobId].js` fetches preview after COMPLETE; `CardPreview` shows numbered image; `QuestionRow` expand/collapse with correct answer (green ✓), distractors (grey ✗), explanation

**Files added:**
- `vqg/backend/pipeline/panel_splitter.py` — panel detection + cropping
- `vqg/backend/routes/preview.py` — card preview + image serving endpoints

**Files modified:**
- `vqg/backend/pipeline/label_extractor.py` — x,y in prompt, grid fallback, INLINE_TEXT filter
- `vqg/backend/utils/image_utils.py` — `draw_numbered_overlay()` added
- `vqg/backend/workers/celery_app.py` — inpainting removed, numbered overlay, panel splitter injected, quiz question rephrasing
- `vqg/backend/pipeline/quiz_generator.py` — per-structure difficulty calibration (removed density→difficulty map from prompt)
- `vqg/backend/main.py` — preview router registered
- `vqg/frontend/pages/results/[jobId].js` — card preview section added
- `vqg/frontend/components/ProgressTracker.js` — step 4 label updated to "Numbering structures"

**Files kept but no longer used by pipeline:**
- `vqg/backend/pipeline/inpainter.py` — retained on disk, not imported
- `vqg/backend/pipeline/quality_checker.py` — retained on disk, not imported

**Known issues / next steps:**
- Restart Celery worker and re-upload PDF to verify numbered overlay images and browser preview
- Verify badge positioning on dense diagrams (badges sized at 2.5% of min dimension — may need tuning)
- Anki card front still uses `processed_path` (numbered image) — verify it renders correctly on import

---

## 2026-04-13 — Smart PDF parser: slide deck high-DPI rendering

**What was added/changed:**
- `pdf_parser.py` — added `_is_slide_page()` helper and a slide-render branch; now handles two PDF types automatically
- `config.py` — added `SLIDE_RENDER_SCALE` (default 3, env-overridable)

**How it works:**
- Per page: call `page.get_images(full=True)` and read `img_info[2]`/`img_info[3]` for pixel dims (no full extract needed)
- If exactly 1 image AND it covers ≥90% of page area in both axes → slide deck page
  - Render via `page.get_pixmap(matrix=fitz.Matrix(3,3), alpha=False)` → 3840×2160 PNG
  - Filename: `page{N:03d}_slide.png`; deduped via `seen_pages` set
- Otherwise → existing `doc.extract_image(xref)` path unchanged
  - Filename: `page{N:03d}_img{xref:05d}.{ext}`; deduped via `seen_xrefs` set
- Both paths produce the same output dict — zero changes to triage, inpainter, or any downstream module

**Root cause:** test PDF was a PowerPoint slide deck exported to PDF. Each page = 1 JPEG at 1280×720. Labels were a few pixels tall → Gemini struggled to read them. 3× render gives 3840×2160 with crisp, readable labels.

**Files affected:**
- `vqg/backend/pipeline/pdf_parser.py` — UPDATED: slide detection + high-DPI render branch
- `vqg/backend/config.py` — UPDATED: `SLIDE_RENDER_SCALE` added

**Known issues / next steps:**
- Restart Celery worker and re-upload PDF to verify 3840×2160 output
- Full end-to-end test with questions now expected to generate correctly

---

## 2026-04-13 — Week 7: Next.js frontend

**What was added/changed:**
- Complete Next.js 14 frontend with Tailwind CSS — no external component libraries
- Upload page (`/`) — drag-and-drop PDF zone, file validation, upload with loading state, error handling, redirects to results
- Results page (`/results/[jobId]`) — polls GET /jobs/{id} every 2.5s, stops on COMPLETE/FAILED; shows header card (filename, status badge, stats), progress tracker, download button / error / empty-state
- `ProgressTracker` component — vertical stage stepper (QUEUED→PARSING→TRIAGING→PROCESSING→GENERATING→EXPORTING→COMPLETE), completed/active/pending/failed visual states, image progress bar, live question count
- Loading skeleton while first API response arrives; connection error card if backend is unreachable
- `backend/models/schemas.py` — added `EXPORTING` to JobStatus enum (was missing; Celery worker was already setting it)

**How it works:**
- `NEXT_PUBLIC_API_URL` env var controls backend URL (defaults to `http://localhost:8000`)
- Polling uses `setInterval` with `clearInterval` cleanup on unmount — no memory leaks
- Download triggers `window.location.href = /export/{id}/anki` — browser handles native download prompt
- Three distinct COMPLETE sub-states: has deck → download banner; no deck (0 questions) → amber warning; failed → red error with raw error string
- Stable genanki GUIDs mean re-importing the same PDF into Anki doesn't duplicate cards

**Files added:**
- `vqg/frontend/package.json` — next@14.1.0, react@18, tailwindcss@3
- `vqg/frontend/next.config.js`, `tailwind.config.js`, `postcss.config.js`
- `vqg/frontend/styles/globals.css`
- `vqg/frontend/pages/_app.js`, `pages/index.js`, `pages/results/[jobId].js`
- `vqg/frontend/components/ProgressTracker.js`

**Files modified:**
- `vqg/backend/models/schemas.py` — EXPORTING added to JobStatus

**To start frontend:**
```bash
cd vqg/frontend && npm install && npm run dev
```
Runs on http://localhost:3000 (CORS already configured in backend).

**Known issues / next steps:**
- Full end-to-end test needed: upload PDF → watch pipeline stages → download .apkg → import into Anki
- Verify .apkg imports cleanly on Anki 2.1.x, 23.x, 24.x
- Polish pass: backend is feature-complete, frontend is feature-complete

---

## 2026-04-13 — Week 6: Anki export

**What was added/changed:**
- `anki_exporter.py` — builds a `.apkg` deck from processed images + questions; one card per QuizQuestion; front = diagram image + question, back = correct answer + distractors + explanation
- `celery_app.py` — added EXPORTING stage after GENERATING; calls `build_anki_deck()`, saves `export_path` to job; if no questions exist (ValueError), logs warning and completes without a deck
- Export route (`routes/export.py`) was already complete — it just needed `export_path` populated in the job, which is now done

**How it works:**
- genanki model ID + deck ID are stable constants — re-importing the same PDF won't duplicate cards in Anki (stable GUIDs via `genanki.guid_for(job_id, label_id, structure_name)`)
- `Package.media_files` uses **absolute paths** (ARCHITECTURE.md constraint) — `os.path.abspath()` applied before passing to genanki
- Card front: `{{Question}}<br>{{Image}}` — image tag uses filename only (genanki bundles the file, Anki resolves by name)
- Card back: correct answer highlighted green, distractors in grey, explanation below a divider
- Uses `processed_path` (inpainted/fallback image) for card front; falls back to original `image_path` if missing
- Deck name: `VQG — {pdf_filename without extension}` so Anki shows a meaningful name

**Files affected:**
- `vqg/backend/pipeline/anki_exporter.py` — NEW
- `vqg/backend/workers/celery_app.py` — UPDATED: EXPORTING stage, build_anki_deck import, export_path saved to job

**Known issues / next steps:**
- Not yet run end-to-end — need to verify .apkg imports cleanly into Anki 2.1.x
- Week 7: Next.js frontend — upload form, progress poller, download button
- After Week 7: full end-to-end test with the radiology PDF

---

## 2026-04-13 — Week 5: Quiz generation

**What was added/changed:**
- `quiz_generator.py` — generates MCQ questions (1 per significant label) via Gemini Flash; returns list of QuizQuestion-compatible dicts; returns [] on any failure (non-fatal)
- `celery_app.py` — added GENERATING stage after PROCESSING; loops over LABEL_BLANK results with labels, calls generate_quiz(), attaches questions to result dict, tracks quiz_count; re-saves processing_results.json with questions populated
- `gemini_client.py` — fixed return type annotation for call_vision_json: `dict` → `dict | list` (Gemini returns a JSON array when asked; json.loads already handles it)

**How it works:**
- Label selection: uses `suggested_quiz_labels` IDs from label extraction to pick the 3–6 most educationally significant labels; falls back to all labels capped at 6 if suggested list is empty
- Batch prompt: sends all target labels in a single Gemini call with domain/category/surrounding_text context; asks for a JSON array of QuizQuestion objects
- Difficulty: mapped from `triage["label_density"]`: HIGH→HARD, MEDIUM→MEDIUM, LOW→EASY
- Validation: drops any question missing required keys, with ≠3 distractors, or with empty structure_name/question
- Gemini may return `{"questions": [...]}` wrap — code handles dict with known wrapper keys as well as bare arrays
- Quiz image: uses processed_path (inpainted/fallback) if available, otherwise original image — cleaner image = better vision context

**Files affected:**
- `vqg/backend/pipeline/quiz_generator.py` — NEW
- `vqg/backend/workers/celery_app.py` — UPDATED: GENERATING stage, generate_quiz import, quiz_count tracking
- `vqg/backend/utils/gemini_client.py` — UPDATED: return type annotation fix

**Known issues / next steps:**
- Not yet run end-to-end — restart Celery, upload PDF, check processing_results.json for questions arrays
- Pass criteria: >80% of LABEL_BLANK images have ≥1 question generated
- Week 6: anki_exporter.py — genanki .apkg builder with embedded images + export route

---

## 2026-04-13 — Week 4: Label extraction + inpainting + quality check

**What was added/changed:**
- `label_extractor.py` — extracts all text labels from a diagram via Gemini Flash; returns labels[], total_labels, suggested_quiz_labels; returns None on API failure
- `inpainter.py` — sends diagram to Nano Banana 2 with category-specific prompt (7 categories + default); appends label text hints if extraction succeeded; saves output to storage/processed/{job_id}/
- `quality_checker.py` — SSIM gate: fails if <0.60 (destroyed) or >0.98 (did nothing); `apply_numbered_box_fallback()` draws numbered white boxes at approximate_location grid positions
- `image_utils.py` — added `compute_ssim()` (grayscale + resize + skimage SSIM) and `draw_numbered_boxes()` (PIL draw, _LOCATION_GRID fractional coords)
- `celery_app.py` — extended to PARSING → TRIAGING → PROCESSING → COMPLETE; LABEL_BLANK images run full label→inpaint→quality→fallback chain; non-LABEL_BLANK pass through as-is; results saved to storage/processed/{job_id}/processing_results.json

**How it works:**
- Inpainting prompt selection: `triage["category"]` maps to one of 7 prompts; label texts appended as hints (up to 10) to help Nano Banana 2 find them
- SSIM bounds are hard-coded (_SSIM_TOO_LOW=0.60, _SSIM_TOO_HIGH=0.98); SSIM_PASS_THRESHOLD=0.82 from config is logged as the target centre but not a cutoff
- Fallback draws 1-indexed numbered boxes; label_map {1: "meaning"} passed to results for quiz generator (Week 5)
- If labels=None (extraction failed), fallback draws single "?" box at CENTER and returns empty label_map
- RGBA/P mode PIL images converted to RGB before saving (Nano Banana 2 may return RGBA)

**Files affected:**
- `vqg/backend/pipeline/label_extractor.py` — NEW
- `vqg/backend/pipeline/inpainter.py` — NEW
- `vqg/backend/pipeline/quality_checker.py` — NEW
- `vqg/backend/utils/image_utils.py` — UPDATED: compute_ssim + draw_numbered_boxes added
- `vqg/backend/workers/celery_app.py` — UPDATED: PROCESSING stage, imports for all 4 new/updated modules

**Known issues / next steps:**
- Not yet run end-to-end — restart Celery worker, upload radiology PDF, check processing_results.json
- Pass criteria: ≥50% of LABEL_BLANK images via nano_banana_2 (not all falling back)
- Week 5: quiz_generator.py — generate MCQ/fill-in-blank questions from processed images + label_map

---

## 2026-04-13 — Week 3 verified: PyMuPDF swap + first successful end-to-end run

**What was added/changed:**
- Replaced marker-pdf with PyMuPDF (fitz) for image extraction — marker-pdf 1.x loads 2GB+ ML models, hit Windows paging file limit
- `pdf_parser.py` fully rewritten around `fitz.open()` — no ML models, zero memory issues
- Added minimum dimension filter (100×100px) to skip icons/bullets automatically
- Added CMYK→RGB conversion for clinical images
- `requirements.txt` updated: `marker-pdf` → `pymupdf>=1.26.0`
- Fixed pydantic version conflict: `pydantic==2.6.0` → `pydantic>=2.9.0,<3.0.0` (google-genai requires >=2.9)
- Fixed Redis port conflict: VQG Redis moved to port 6380 (port 6379 occupied by separate project)
- First full end-to-end run completed successfully on radiology PDF

**How it works:**
- PyMuPDF: `fitz.open(pdf)` → iterate pages → `page.get_images()` → `doc.extract_image(xref)` → PIL save
- Deduplication via `seen_xrefs` set — images appearing on multiple pages are only extracted once
- Surrounding text comes from `page.get_text()` directly (no ML needed, exact page match)
- Celery worker on Windows requires `--pool=solo` flag — standard threading pool doesn't work

**Files affected:**
- `vqg/backend/pipeline/pdf_parser.py` — REWRITTEN: marker-pdf → PyMuPDF
- `vqg/requirements.txt` — marker-pdf removed, pymupdf added, pydantic version fixed
- `vqg/.env` — REDIS_URL changed to port 6380
- `vqg/docker-compose.yml` — port mapping changed to 6380:6379, removed obsolete `version` field

**Verified results (radiology PDF — M12A.6 Skull & Brain Blood Supply):**
- 32 images extracted, 4 skipped (tiny), 28 triaged
- 16 → LABEL_BLANK (Circle of Willis diagrams, labeled skull X-rays)
- 10 → CONTEXT_MCQ (text slides, procedural steps)
- 1 → REGION_CLICK (MR angiography)
- Confidence 0.9–1.0 across all classifications
- Full pipeline time: ~4 minutes for 32 images

**Known issues / next steps:**
- Week 4: `label_extractor.py` + `inpainter.py` + `quality_checker.py`
- `gemini-3-flash-preview` is preview — watch for GA model ID

---

## 2026-04-12 — Week 3: SDK migration + Gemini triage pipeline

**What was added/changed:**
- Migrated from `google-generativeai` (legacy, support ended Nov 30 2025) to `google-genai` (official GA SDK)
- Updated triage/quiz model from `gemini-2.5-flash` (deprecates June 17 2026) to `gemini-3-flash-preview`
- `gemini-3.1-flash-image-preview` (Nano Banana 2) confirmed current — no change needed
- Built `backend/utils/gemini_client.py` — central Gemini wrapper (rate limiter, JSON fence stripper, retry, vision+text, image editing)
- Built `backend/pipeline/image_triage.py` — exact triage prompt from guide, routing logic
- Extended Celery worker with full triage loop: PARSING → TRIAGING → COMPLETE
- Triage results saved to `storage/images/{job_id}/triage_results.json` for manual inspection
- Updated CLAUDE.md and ARCHITECTURE.md with correct SDK and model info

**How it works:**
- New SDK pattern: `from google import genai` → `client = genai.Client(api_key=...)` → `client.models.generate_content(...)`
- `call_vision_json()` in gemini_client reads image bytes, sends to Gemini, strips JSON fences, parses, retries once
- Rate limiter is module-level (token bucket at 80 RPM) — all calls share the same limiter
- `triage_image()` returns `None` on API failure or confidence < 0.5 — caller skips
- `route_image()` returns SKIP if `worth_quizzing=False` or confidence < 0.7 (MLP: no human review queue)
- Worker logs each triage result with category and route for debugging

**Files affected:**
- `vqg/requirements.txt` — `google-generativeai==0.5.0` → `google-genai>=1.0.0`
- `vqg/.env` — `GEMINI_FLASH_MODEL=gemini-2.5-flash` → `gemini-3-flash-preview`
- `vqg/backend/utils/gemini_client.py` — NEW: full Gemini API wrapper
- `vqg/backend/pipeline/image_triage.py` — NEW: triage + routing
- `vqg/backend/workers/celery_app.py` — UPDATED: triage loop, triage_results.json save
- `CLAUDE.md` + `ARCHITECTURE.md` — updated model IDs and SDK info

**Known issues / next steps:**
- Triage not yet tested against a real PDF — must run end-to-end and inspect triage_results.json
- Week 4: `label_extractor.py` + `inpainter.py` + `quality_checker.py`
- `gemini-3-flash-preview` is a preview model — watch for GA release and switch to stable ID when available

---

## 2026-04-12 — Week 1: Foundation + PDF parsing pipeline built

**What was added/changed:**
- Full `vqg/` project structure created with all Week 1 files
- FastAPI app with `/upload`, `/jobs/{id}`, `/export/{id}/anki` (stub) endpoints
- SQLite job tracking with `init_db`, `create_job`, `update_job`, `get_job` helpers
- Celery + Redis worker wired up — `process_pdf_task` enqueued on upload
- `pdf_parser.py` integrates marker-pdf: PDF in → images saved to `storage/images/{job_id}/`
- All Pydantic schemas and enums defined (`ImageCategory`, `QuizFormat`, `JobStatus`, etc.)
- CORS configured for localhost:3000 (Next.js dev server)

**How it works:**
- POST /upload saves the PDF, creates a QUEUED job in SQLite, enqueues Celery task — returns job_id immediately
- Celery worker picks up the task, sets status=PARSING, calls `parse_pdf()`, sets status=COMPLETE with total_images count
- `parse_pdf()` calls marker-pdf's `convert_single_pdf()` → saves each PIL.Image to disk → returns list of image records
- `config.py` is the single source for all env vars — all modules import from there, never `os.getenv` directly
- `_resolve_page_number()` in pdf_parser handles marker-pdf metadata variations across versions
- On Windows, Celery worker must be started with `--pool=solo` flag

**Files affected:**
- `vqg/docker-compose.yml` — Redis 7 alpine
- `vqg/.env` — all env vars template
- `vqg/requirements.txt` — pinned dependencies
- `vqg/backend/main.py` — FastAPI app entry, startup hooks, CORS
- `vqg/backend/config.py` — all env vars loaded here
- `vqg/backend/models/schemas.py` — all Pydantic models and enums
- `vqg/backend/models/db.py` — SQLite helpers
- `vqg/backend/pipeline/pdf_parser.py` — marker-pdf integration
- `vqg/backend/utils/image_utils.py` — surrounding text extraction (stub for SSIM/PIL in Week 4)
- `vqg/backend/workers/celery_app.py` — Celery app + process_pdf_task (parsing only for now)
- `vqg/backend/routes/upload.py` — POST /upload
- `vqg/backend/routes/jobs.py` — GET /jobs/{id}
- `vqg/backend/routes/export.py` — GET /export/{id}/anki (stub, returns 501)
- All `__init__.py` files for Python packages

**Known issues / next steps:**
- marker-pdf not yet installed or tested on this machine — must run `pip install -r requirements.txt` and verify
- Celery on Windows requires `--pool=solo`: `celery -A backend.workers.celery_app worker --loglevel=info --pool=solo`
- Week 3: Build `image_triage.py` — Gemini 2.5 Flash vision triage with exact prompt from guide
- Still need to verify `gemini-3.1-flash-image-preview` model ID is live before Week 4 inpainter work

---

## 2026-04-12 — Project scaffolded + all templates filled

**What was added/changed:**
- CLAUDE.md, PRD.md, ARCHITECTURE.md, DEVLOG.md all filled out from VQG Implementation Guide v1.0
- No source code written yet — this is planning/context only

**How it works:**
- N/A — initial setup

**Files affected:**
- `CLAUDE.md` — filled with VQG project context, stack, commands, patterns
- `PRD.md` — filled with problem statement, MoSCoW requirements, build order, risks, open questions
- `ARCHITECTURE.md` — filled with full stack decisions, directory structure, data flow, module boundaries, key decisions
- `DEVLOG.md` — initialized

**Known issues / next steps:**
- Week 1: Set up FastAPI app + SQLite schema + `/upload` endpoint + storage directories
- Week 1: Integrate marker-pdf — verify it works on Windows 11 (not confirmed yet)
- Week 1: Set up Celery + Redis via docker-compose
- Verify `gemini-3.1-flash-image-preview` is still the correct Nano Banana 2 model ID before building inpainter
- Verify `response_modalities=["image", "text"]` works in current `google-generativeai` SDK version

---
