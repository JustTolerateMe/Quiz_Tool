# PRD — VQG (Visual Quiz Generator)

> Source of truth for what we're building. Update when scope changes. Claude reads this at session start.

---

## Problem

Medical and biology students spend enormous time manually creating Anki flashcards from diagrams in textbooks. They screenshot images, blank out labels in image editors, and type questions by hand. This takes 2–5 minutes per card. A 20-page anatomy chapter can contain 30+ diagrams. The process is tedious enough that most students skip it and rely on text-only cards, which are proven to be less effective for spatial/visual learning.

**VQG automates this entirely:** upload a PDF → get an Anki deck with visual quiz cards in minutes.

---

## Goals

| Goal | How we measure it |
|------|-------------------|
| Process a 20-page anatomy PDF end-to-end | Full pipeline test: PDF in → .apkg out, no crashes |
| Produce plausible MCQ distractors | Manual review of 50 questions: >80% have all-plausible distractors |
| Inpainting removes labels without destroying diagrams | SSIM between 0.60–0.98 on >70% of processed images |
| .apkg imports cleanly into Anki desktop | Test on Anki 2.1.x, 23.x, 24.x — images display correctly |
| Full pipeline completes in <5 min per 15-image PDF | Timed end-to-end test |

---

## Not in scope (this version)

- Multi-user accounts / authentication
- Cloud storage (Cloudflare R2) — local filesystem only for MLP
- Manual review UI for triage overrides
- Mobile app or Anki plugin
- Support for scanned PDFs (OCR fallback is low priority for MLP)
- Batch upload of multiple PDFs
- Image Occlusion format (standard MCQ format only for now)

---

## Users

**Primary:** Medical / biology / chemistry students who already use Anki and study from PDF textbooks. They know what a good flashcard looks like. They care deeply about distractor quality. They are technical enough to install Anki and import a .apkg.

**Secondary:** Not targeted in this version.

---

## Requirements

### Must have — launch is blocked without these
- [ ] Upload a PDF via web UI → job queued and tracked
- [ ] Extract all images from PDF (marker-pdf integration)
- [ ] Triage each image: classify type, route to correct processing path, skip non-quiz-worthy
- [ ] For LABEL_BLANK images: extract labels with Gemini Vision
- [ ] Inpaint labels using Nano Banana 2 (gemini-3.1-flash-image-preview)
- [ ] SSIM quality check on inpainted image + fallback to numbered box overlay
- [ ] Generate MCQ questions + 3 distractors per label with Gemini 2.5 Flash
- [ ] Export valid .apkg Anki deck with embedded images
- [ ] Job status polling endpoint (`GET /jobs/{id}`)
- [ ] Download endpoint for completed deck (`GET /export/{id}/anki`)

### Should have — important but not blocking
- [ ] Celery + Redis async worker (so slow inpainting doesn't block the API)
- [ ] Rate limiting on Gemini calls (stay under 150 RPM Tier 1 limit)
- [ ] Retry logic on Gemini API failures (retry once, then skip image)
- [ ] Progress tracking (images processed / total) visible in frontend

### Could have — nice to have, low effort
- [ ] SEQUENCE_ORDER quiz format for flowcharts (scramble steps)
- [ ] DATA_READING quiz format for charts (extract values, generate reading questions)
- [ ] Surrounding PDF text passed to quiz generator for better context

### Won't have — explicitly deferred
- Manual triage override UI — needs more infrastructure, defer to v2
- PostgreSQL — SQLite is sufficient for first 20 users
- Cloudflare R2 — local filesystem is sufficient for MLP
- Auth / user accounts — single-user tool for MLP

---

## Non-functional requirements

| Concern | Requirement |
|---------|-------------|
| Performance | Full pipeline < 5 minutes for a PDF with 15 quizzable images |
| Offline | Not required — Gemini API calls are online only |
| Security | API key in .env only. No user data logged. |
| Privacy | No analytics. No external requests except Gemini API. |
| Compatibility | Anki 2.1.x, 23.x, 24.x — .apkg must import on all three |
| Cost | Stay under $3.50/user/month at 45 images processed (3 PDFs × 15 images) |

---

## Build order

1. **Foundation** — FastAPI app, SQLite schema, `/upload` endpoint, job creation, storage directories, Celery + Redis wiring
2. **PDF Parsing** — marker-pdf integration, image extraction, surrounding text extraction
3. **Triage** — Gemini Vision triage with exact prompt from guide, routing logic
4. **Inpainting** — label extractor, Nano Banana 2 inpainter, SSIM quality check, numbered box fallback
5. **Quiz generation** — MCQ + distractor generation with Gemini 2.5 Flash
6. **Anki export** — genanki .apkg builder with embedded images
7. **Frontend** — Next.js upload page, progress tracker, download button
8. **Polish** — Error handling on all API calls, rate limiting, end-to-end test with real anatomy PDF

---

## Data model

```
Job {
  job_id: UUID string
  status: QUEUED | PARSING | TRIAGING | PROCESSING | GENERATING | COMPLETE | FAILED
  pdf_filename: string
  total_images: int
  processed_images: int
  skipped_images: int
  quiz_count: int
  export_path: string | null
  error: string | null
  created_at: ISO string
  updated_at: ISO string
}

ProcessedImage {
  image_id: string          // filename from marker-pdf
  original_path: string
  processed_path: string | null
  method: nano_banana_2 | numbered_box_fallback | skipped
  triage: TriageResult      // full JSON from triage step
  labels: LabelExtractionResult | null
  questions: QuizQuestion[] | null
  ssim_score: float | null
}

QuizQuestion {
  label_id: string
  structure_name: string    // correct answer
  question: string
  distractors: string[3]
  difficulty: EASY | MEDIUM | HARD
  explanation: string
}
```

---

## Risks

| Risk | Likelihood | Impact | How to handle |
|------|-----------|--------|---------------|
| Nano Banana 2 model ID changes or is deprecated | Medium | High | Verify model ID before building inpainter. Check Gemini changelog. |
| Inpainting destroys diagram structure | Medium | High | SSIM check catches this. Numbered box fallback is always available. |
| marker-pdf fails on complex PDFs | Medium | Medium | Test on 5 different PDFs before declaring parser done. Log failures. |
| Gemini JSON responses malformed | High | Low | Always strip fences. Retry once. Skip image on second failure. |
| Distractor quality poor for niche domains | Medium | Medium | Flag AI-generated questions as "unverified" in card metadata. |
| Anki .apkg media files missing | Low | High | Verify genanki Package.media_files uses absolute paths. Test import before shipping. |

---

## Open questions

- [ ] Does `gemini-3.1-flash-image-preview` support `response_modalities=["image", "text"]` in the current Python SDK version? Verify before building inpainter.
- [ ] Does marker-pdf 0.2.17 work on Windows? (Primary dev environment is Windows 11)
- [ ] What is the actual RPM limit for gemini-3.1-flash-image-preview on Tier 1? Rate limiter is currently set to 100 RPM assuming Flash limits — may need adjustment.
