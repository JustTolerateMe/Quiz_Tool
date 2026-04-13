import { useEffect, useRef, useState } from 'react'
import { useRouter } from 'next/router'
import Head from 'next/head'
import Link from 'next/link'
import ProgressTracker from '../../components/ProgressTracker'

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
const POLL_INTERVAL_MS = 2500

const TERMINAL_STATUSES = new Set(['COMPLETE', 'FAILED'])

const DIFFICULTY_COLOURS = {
  EASY:   'bg-emerald-50 text-emerald-700',
  MEDIUM: 'bg-amber-50 text-amber-700',
  HARD:   'bg-red-50 text-red-700',
}

export default function ResultsPage() {
  const router = useRouter()
  const { jobId } = router.query

  const [job, setJob]           = useState(null)
  const [fetchError, setFetchError] = useState('')
  const [preview, setPreview]   = useState(null)
  const intervalRef = useRef(null)

  useEffect(() => {
    if (!jobId) return

    const poll = async () => {
      try {
        const res = await fetch(`${API_URL}/jobs/${jobId}`)
        if (!res.ok) {
          if (res.status === 404) {
            setFetchError('Job not found. It may have expired or never existed.')
            clearInterval(intervalRef.current)
            return
          }
          throw new Error(`Server returned ${res.status}`)
        }
        const data = await res.json()
        setJob(data)
        setFetchError('')
        if (TERMINAL_STATUSES.has(data.status)) {
          clearInterval(intervalRef.current)
          // Fetch preview once job is complete
          if (data.status === 'COMPLETE') {
            try {
              const pr = await fetch(`${API_URL}/jobs/${jobId}/preview`)
              if (pr.ok) setPreview(await pr.json())
            } catch (_) { /* preview is optional */ }
          }
        }
      } catch (err) {
        setFetchError(`Could not reach the backend: ${err.message}`)
      }
    }

    poll()
    intervalRef.current = setInterval(poll, POLL_INTERVAL_MS)
    return () => clearInterval(intervalRef.current)
  }, [jobId])

  const handleDownload = () => {
    window.location.href = `${API_URL}/export/${jobId}/anki`
  }

  const isComplete = job?.status === 'COMPLETE'
  const isFailed   = job?.status === 'FAILED'
  const hasExport  = isComplete && job?.export_path
  const title = job ? `${job.pdf_filename} — VQG` : 'Processing… — VQG'

  return (
    <>
      <Head><title>{title}</title></Head>

      <div className="min-h-screen bg-slate-50 px-4 py-10">
        <div className="max-w-2xl mx-auto">

          {/* Back link */}
          <Link
            href="/"
            className="inline-flex items-center gap-1.5 text-sm text-slate-500 hover:text-slate-800 transition-colors mb-8"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M10.5 19.5L3 12m0 0l7.5-7.5M3 12h18" />
            </svg>
            New upload
          </Link>

          {/* Loading skeleton */}
          {!job && !fetchError && (
            <div className="bg-white rounded-2xl border border-slate-200 shadow-sm p-8">
              <div className="animate-pulse space-y-4">
                <div className="h-5 bg-slate-100 rounded w-2/3" />
                <div className="h-3 bg-slate-100 rounded w-1/3" />
                <div className="mt-6 space-y-3">
                  {[...Array(5)].map((_, i) => (
                    <div key={i} className="flex items-center gap-3">
                      <div className="w-8 h-8 bg-slate-100 rounded-full flex-shrink-0" />
                      <div className="h-3 bg-slate-100 rounded flex-1" />
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}

          {/* Fetch error */}
          {fetchError && (
            <div className="bg-white rounded-2xl border border-red-100 shadow-sm p-6">
              <div className="flex items-start gap-3">
                <div className="w-9 h-9 rounded-full bg-red-100 flex items-center justify-center flex-shrink-0">
                  <svg className="w-5 h-5 text-red-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
                  </svg>
                </div>
                <div>
                  <p className="text-sm font-semibold text-slate-800">Connection error</p>
                  <p className="text-sm text-slate-500 mt-1">{fetchError}</p>
                  <p className="text-xs text-slate-400 mt-2">Make sure the backend is running on port 8000.</p>
                </div>
              </div>
            </div>
          )}

          {/* Main job card */}
          {job && (
            <div className="space-y-4">

              {/* Header card */}
              <div className="bg-white rounded-2xl border border-slate-200 shadow-sm px-6 py-5">
                <div className="flex items-start justify-between gap-4">
                  <div className="min-w-0">
                    <h1 className="text-base font-semibold text-slate-900 truncate">{job.pdf_filename}</h1>
                    <p className="text-xs text-slate-400 mt-0.5 font-mono">{jobId}</p>
                  </div>
                  <span className={`flex-shrink-0 inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold
                    ${isComplete ? 'bg-emerald-50 text-emerald-700' : isFailed ? 'bg-red-50 text-red-700' : 'bg-indigo-50 text-indigo-700'}`}
                  >
                    {!isComplete && !isFailed && <span className="w-1.5 h-1.5 rounded-full bg-indigo-500 animate-pulse" />}
                    {isComplete && (
                      <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
                      </svg>
                    )}
                    {isFailed && (
                      <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                      </svg>
                    )}
                    {job.status}
                  </span>
                </div>

                {job.total_images > 0 && (
                  <div className="mt-4 pt-4 border-t border-slate-100 grid grid-cols-3 gap-4">
                    <Stat label="Images found" value={job.total_images} />
                    <Stat label="Processed" value={job.processed_images} />
                    <Stat label="Questions" value={job.quiz_count} highlight={job.quiz_count > 0} />
                  </div>
                )}
              </div>

              {/* Progress tracker */}
              <div className="bg-white rounded-2xl border border-slate-200 shadow-sm px-6 py-6">
                <ProgressTracker
                  status={job.status}
                  totalImages={job.total_images}
                  processedImages={job.processed_images}
                  generatedImages={job.generated_images}
                  quizCount={job.quiz_count}
                />
              </div>

              {/* Complete — download */}
              {isComplete && hasExport && (
                <div className="bg-emerald-50 border border-emerald-100 rounded-2xl px-6 py-5">
                  <div className="flex items-center gap-3 mb-4">
                    <div className="w-9 h-9 rounded-full bg-emerald-100 flex items-center justify-center flex-shrink-0">
                      <svg className="w-5 h-5 text-emerald-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                      </svg>
                    </div>
                    <div>
                      <p className="text-sm font-semibold text-emerald-900">Your deck is ready</p>
                      <p className="text-xs text-emerald-700 mt-0.5">
                        {job.quiz_count} card{job.quiz_count !== 1 ? 's' : ''} · Import into Anki to start studying
                      </p>
                    </div>
                  </div>
                  <button
                    onClick={handleDownload}
                    className="w-full py-3 px-4 rounded-xl bg-emerald-600 hover:bg-emerald-700 active:scale-[0.98] text-white font-semibold text-sm transition-all shadow-sm flex items-center justify-center gap-2"
                  >
                    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5M16.5 12L12 16.5m0 0L7.5 12m4.5 4.5V3" />
                    </svg>
                    Download vqg_{jobId.slice(0, 8)}.apkg
                  </button>
                </div>
              )}

              {/* Complete but no questions */}
              {isComplete && !hasExport && (
                <div className="bg-amber-50 border border-amber-100 rounded-2xl px-6 py-5">
                  <div className="flex items-start gap-3">
                    <div className="w-9 h-9 rounded-full bg-amber-100 flex items-center justify-center flex-shrink-0 mt-0.5">
                      <svg className="w-5 h-5 text-amber-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
                      </svg>
                    </div>
                    <div>
                      <p className="text-sm font-semibold text-amber-900">Processing complete, but no quiz cards were generated</p>
                      <p className="text-sm text-amber-800 mt-1">
                        This PDF may not contain labelled diagrams, or all images were classified as not quiz-worthy.
                      </p>
                      <Link href="/" className="inline-block mt-3 text-sm font-medium text-amber-700 hover:text-amber-900 underline underline-offset-2">
                        Try a different PDF
                      </Link>
                    </div>
                  </div>
                </div>
              )}

              {/* Failed */}
              {isFailed && (
                <div className="bg-red-50 border border-red-100 rounded-2xl px-6 py-5">
                  <div className="flex items-start gap-3">
                    <div className="w-9 h-9 rounded-full bg-red-100 flex items-center justify-center flex-shrink-0 mt-0.5">
                      <svg className="w-5 h-5 text-red-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                      </svg>
                    </div>
                    <div>
                      <p className="text-sm font-semibold text-red-900">Processing failed</p>
                      {job.error && <p className="text-xs text-red-700 mt-1 font-mono break-all">{job.error}</p>}
                      <Link href="/" className="inline-block mt-3 text-sm font-medium text-red-700 hover:text-red-900 underline underline-offset-2">
                        Try again
                      </Link>
                    </div>
                  </div>
                </div>
              )}

              {/* ── Card Preview ── */}
              {preview && preview.cards.length > 0 && (
                <div className="space-y-4">
                  <div className="flex items-center justify-between px-1">
                    <h2 className="text-sm font-semibold text-slate-700">
                      Card preview — {preview.card_count} card{preview.card_count !== 1 ? 's' : ''}
                    </h2>
                    <span className="text-xs text-slate-400">Click any question to reveal answer</span>
                  </div>

                  {preview.cards.map((card, ci) => (
                    <CardPreview key={ci} card={card} apiUrl={API_URL} />
                  ))}
                </div>
              )}

            </div>
          )}
        </div>
      </div>
    </>
  )
}

function CardPreview({ card, apiUrl }) {
  const imgSrc = card.numbered_image_url
    ? `${apiUrl}${card.numbered_image_url}`
    : card.original_image_url
      ? `${apiUrl}${card.original_image_url}`
      : null

  return (
    <div className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden">
      {/* Diagram */}
      {imgSrc && (
        <div className="bg-slate-50 border-b border-slate-100 p-3">
          <img
            src={imgSrc}
            alt={card.image_id}
            className="w-full object-contain rounded-lg"
            style={{ maxHeight: 480 }}
          />
          {card.panel_description && (
            <p className="text-xs text-slate-400 mt-2 text-center italic">{card.panel_description}</p>
          )}
        </div>
      )}

      {/* Questions */}
      <div className="divide-y divide-slate-100">
        {card.questions.map((q, qi) => (
          <QuestionRow key={qi} q={q} />
        ))}
      </div>
    </div>
  )
}

function QuestionRow({ q }) {
  const [open, setOpen] = useState(false)
  const diffClass = DIFFICULTY_COLOURS[q.difficulty] || 'bg-slate-100 text-slate-600'

  return (
    <div className="px-5 py-4">
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium text-slate-800">{q.question}</p>
        </div>
        <div className="flex items-center gap-2 flex-shrink-0">
          <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${diffClass}`}>
            {q.difficulty}
          </span>
          <button
            onClick={() => setOpen(o => !o)}
            className="text-xs text-indigo-600 hover:text-indigo-800 font-medium whitespace-nowrap"
          >
            {open ? 'Hide' : 'Show answer'}
          </button>
        </div>
      </div>

      {open && (
        <div className="mt-3 space-y-2">
          {/* Correct answer */}
          <div className="flex items-center gap-2">
            <span className="w-5 h-5 rounded-full bg-emerald-100 flex items-center justify-center flex-shrink-0">
              <svg className="w-3 h-3 text-emerald-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
              </svg>
            </span>
            <span className="text-sm font-semibold text-emerald-700">{q.structure_name}</span>
          </div>

          {/* Distractors */}
          {q.distractors.map((d, i) => (
            <div key={i} className="flex items-center gap-2">
              <span className="w-5 h-5 rounded-full bg-slate-100 flex items-center justify-center flex-shrink-0">
                <svg className="w-3 h-3 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </span>
              <span className="text-sm text-slate-500 line-through">{d}</span>
            </div>
          ))}

          {/* Explanation */}
          {q.explanation && (
            <p className="text-xs text-slate-500 mt-2 pt-2 border-t border-slate-100 leading-relaxed">
              {q.explanation}
            </p>
          )}
        </div>
      )}
    </div>
  )
}

function Stat({ label, value, highlight }) {
  return (
    <div className="text-center">
      <p className={`text-xl font-bold ${highlight ? 'text-indigo-600' : 'text-slate-900'}`}>{value}</p>
      <p className="text-xs text-slate-400 mt-0.5">{label}</p>
    </div>
  )
}
