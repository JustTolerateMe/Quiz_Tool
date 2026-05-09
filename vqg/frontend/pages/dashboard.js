import { useEffect, useState } from 'react'
import { useSession, signIn } from 'next-auth/react'
import Head from 'next/head'
import Link from 'next/link'

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

const STATUS_STYLES = {
  COMPLETE:        'bg-emerald-100 text-emerald-700',
  FAILED:          'bg-red-100 text-red-600',
  AWAITING_REVIEW: 'bg-amber-100 text-amber-700',
  QUEUED:          'bg-slate-100 text-slate-500',
  PARSING:         'bg-indigo-100 text-indigo-600',
  TRIAGING:        'bg-indigo-100 text-indigo-600',
  PROCESSING:      'bg-indigo-100 text-indigo-600',
  GENERATING:      'bg-indigo-100 text-indigo-600',
  EXPORTING:       'bg-indigo-100 text-indigo-600',
}

function formatDate(iso) {
  return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
}

export default function Dashboard() {
  const { data: session, status } = useSession()
  const [jobs, setJobs] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (status === 'loading') return
    if (!session) { setLoading(false); return }

    fetch(`${API_URL}/jobs`, {
      headers: { 'x-user-id': session.user.email },
    })
      .then(r => r.json())
      .then(data => { setJobs(data.jobs || []); setLoading(false) })
      .catch(() => setLoading(false))
  }, [session, status])

  if (status === 'loading' || loading) {
    return (
      <div className="min-h-screen bg-slate-50 flex items-center justify-center">
        <div className="animate-spin w-6 h-6 border-2 border-indigo-500 border-t-transparent rounded-full" />
      </div>
    )
  }

  if (!session) {
    return (
      <div className="min-h-screen bg-slate-50 flex flex-col items-center justify-center gap-4">
        <p className="text-slate-600">Sign in to see your quiz history.</p>
        <button
          onClick={() => signIn('google')}
          className="px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm font-medium hover:bg-indigo-700"
        >
          Sign in with Google
        </button>
      </div>
    )
  }

  return (
    <>
      <Head>
        <title>My Jobs — VQG</title>
      </Head>

      <div className="min-h-screen bg-slate-50 px-4 py-10">
        <div className="max-w-3xl mx-auto">

          {/* Header row */}
          <div className="flex items-center justify-between mb-8">
            <div>
              <h1 className="text-2xl font-bold text-slate-900">My Jobs</h1>
              <p className="text-sm text-slate-500 mt-0.5">Quizzes you've generated while signed in</p>
            </div>
            <Link href="/" className="px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm font-medium hover:bg-indigo-700">
              + New quiz
            </Link>
          </div>

          {/* Jobs list */}
          {jobs.length === 0 ? (
            <div className="bg-white rounded-2xl border border-slate-200 p-12 text-center">
              <p className="text-slate-500 text-sm">No quizzes yet.</p>
              <Link href="/" className="mt-3 inline-block text-indigo-600 text-sm font-medium hover:underline">
                Upload your first PDF
              </Link>
            </div>
          ) : (
            <div className="bg-white rounded-2xl border border-slate-200 divide-y divide-slate-100 overflow-hidden">
              {jobs.map(job => (
                <div key={job.job_id} className="flex items-center gap-4 px-5 py-4 hover:bg-slate-50 transition-colors">
                  {/* File icon */}
                  <div className="flex-shrink-0 w-9 h-9 rounded-lg bg-indigo-50 flex items-center justify-center">
                    <svg className="w-4 h-4 text-indigo-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
                    </svg>
                  </div>

                  {/* Info */}
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-slate-800 truncate">{job.pdf_filename}</p>
                    <p className="text-xs text-slate-400 mt-0.5">
                      {formatDate(job.created_at)}
                      {job.quiz_count > 0 && ` · ${job.quiz_count} questions`}
                    </p>
                  </div>

                  {/* Status badge */}
                  <span className={`flex-shrink-0 text-xs font-medium px-2 py-0.5 rounded-full ${STATUS_STYLES[job.status] || 'bg-slate-100 text-slate-500'}`}>
                    {job.status.replace('_', ' ')}
                  </span>

                  {/* Action link */}
                  <Link
                    href={`/results/${job.job_id}`}
                    className="flex-shrink-0 text-xs text-indigo-600 hover:underline font-medium"
                  >
                    {job.status === 'COMPLETE' ? 'View' : 'Track'}
                  </Link>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </>
  )
}
