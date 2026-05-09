import { useState, useRef, useCallback } from 'react'
import { useRouter } from 'next/router'
import Head from 'next/head'
import { useSession, signIn, signOut } from 'next-auth/react'

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

export default function UploadPage() {
  const router = useRouter()
  const fileInputRef = useRef(null)
  const { data: session } = useSession()

  const [selectedFile, setSelectedFile] = useState(null)
  const [dragging, setDragging] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState('')

  const acceptFile = useCallback((file) => {
    if (!file) return
    if (file.type !== 'application/pdf' && !file.name.endsWith('.pdf')) {
      setError('Please select a PDF file.')
      return
    }
    setError('')
    setSelectedFile(file)
  }, [])

  const handleDragOver = (e) => {
    e.preventDefault()
    setDragging(true)
  }

  const handleDragLeave = (e) => {
    e.preventDefault()
    setDragging(false)
  }

  const handleDrop = (e) => {
    e.preventDefault()
    setDragging(false)
    acceptFile(e.dataTransfer.files[0])
  }

  const handleFileChange = (e) => {
    acceptFile(e.target.files[0])
    // reset so same file can be re-selected
    e.target.value = ''
  }

  const handleUpload = async () => {
    if (!selectedFile || uploading) return
    setUploading(true)
    setError('')

    const formData = new FormData()
    formData.append('file', selectedFile)

    try {
      const headers = {}
      if (session?.user?.email) headers['x-user-id'] = session.user.email

      const res = await fetch(`${API_URL}/upload`, {
        method: 'POST',
        headers,
        body: formData,
      })

      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body.detail || `Upload failed (${res.status})`)
      }

      const { job_id } = await res.json()
      router.push(`/results/${job_id}`)
    } catch (err) {
      setError(err.message)
      setUploading(false)
    }
  }

  const removeFile = (e) => {
    e.stopPropagation()
    setSelectedFile(null)
    setError('')
  }

  const formatSize = (bytes) => {
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  }

  return (
    <>
      <Head>
        <title>VQG — Visual Quiz Generator</title>
        <meta name="description" content="Turn PDF diagrams into Anki flashcards automatically" />
      </Head>

      <div className="min-h-screen bg-slate-50 flex flex-col items-center justify-center px-4 py-12">

        {/* Auth bar */}
        <div className="absolute top-4 right-4 flex items-center gap-3">
          {session ? (
            <>
              <a href="/dashboard" className="text-sm text-indigo-600 hover:underline font-medium">My Jobs</a>
              <div className="flex items-center gap-2">
                {session.user.image && (
                  <img src={session.user.image} alt="" className="w-7 h-7 rounded-full" />
                )}
                <span className="text-sm text-slate-600 hidden sm:block">{session.user.name}</span>
              </div>
              <button onClick={() => signOut()} className="text-xs text-slate-400 hover:text-slate-600">Sign out</button>
            </>
          ) : (
            <button
              onClick={() => signIn('google')}
              className="flex items-center gap-2 px-3 py-1.5 rounded-lg border border-slate-200 bg-white text-sm text-slate-700 hover:bg-slate-50 shadow-sm transition-colors"
            >
              <svg className="w-4 h-4" viewBox="0 0 24 24"><path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/><path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/><path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l3.66-2.84z"/><path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/></svg>
              Sign in with Google
            </button>
          )}
        </div>

        {/* Header */}
        <div className="text-center mb-10">
          <div className="inline-flex items-center justify-center w-14 h-14 rounded-2xl bg-indigo-600 mb-5 shadow-lg">
            {/* Brain/diagram icon */}
            <svg className="w-8 h-8 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.75}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M9.75 3.104v5.714a2.25 2.25 0 01-.659 1.591L5 14.5M9.75 3.104c-.251.023-.501.05-.75.082m.75-.082a24.301 24.301 0 014.5 0m0 0v5.714c0 .597.237 1.17.659 1.591L19.8 15.3M14.25 3.104c.251.023.501.05.75.082M19.8 15.3l-1.57.393A9.065 9.065 0 0112 15a9.065 9.065 0 00-6.23-.693L5 14.5m14.8.8l1.402 1.402c1.232 1.232.65 3.318-1.067 3.611A48.309 48.309 0 0112 21c-2.773 0-5.491-.235-8.135-.687-1.718-.293-2.3-2.379-1.067-3.61L5 14.5" />
            </svg>
          </div>
          <h1 className="text-3xl font-bold text-slate-900 tracking-tight">Visual Quiz Generator</h1>
          <p className="mt-2 text-slate-500 text-base max-w-sm mx-auto">
            Upload a PDF textbook. Get an Anki deck with labelled diagrams turned into flashcards.
          </p>
        </div>

        {/* Upload card */}
        <div className="w-full max-w-lg bg-white rounded-2xl shadow-sm border border-slate-200 overflow-hidden">

          {/* Drop zone */}
          <div
            className={`relative m-6 border-2 border-dashed rounded-xl transition-colors cursor-pointer select-none
              ${dragging
                ? 'border-indigo-400 bg-indigo-50'
                : selectedFile
                  ? 'border-indigo-300 bg-indigo-50/50'
                  : 'border-slate-200 hover:border-indigo-300 hover:bg-slate-50'
              }`}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
            onClick={() => !selectedFile && fileInputRef.current.click()}
          >
            <input
              ref={fileInputRef}
              type="file"
              accept=".pdf,application/pdf"
              className="hidden"
              onChange={handleFileChange}
            />

            {selectedFile ? (
              /* File selected state */
              <div className="flex items-center gap-4 p-5">
                <div className="flex-shrink-0 w-10 h-10 rounded-lg bg-indigo-100 flex items-center justify-center">
                  <svg className="w-5 h-5 text-indigo-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
                  </svg>
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-semibold text-slate-800 truncate">{selectedFile.name}</p>
                  <p className="text-xs text-slate-400 mt-0.5">{formatSize(selectedFile.size)}</p>
                </div>
                <button
                  onClick={removeFile}
                  className="flex-shrink-0 w-7 h-7 rounded-full hover:bg-slate-100 flex items-center justify-center text-slate-400 hover:text-slate-600 transition-colors"
                  title="Remove file"
                >
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </div>
            ) : (
              /* Empty / drag state */
              <div className="flex flex-col items-center justify-center py-12 px-6 text-center">
                <div className={`w-12 h-12 rounded-full flex items-center justify-center mb-4 transition-colors ${dragging ? 'bg-indigo-100' : 'bg-slate-100'}`}>
                  <svg className={`w-6 h-6 transition-colors ${dragging ? 'text-indigo-500' : 'text-slate-400'}`} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.75}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5" />
                  </svg>
                </div>
                <p className="text-sm font-medium text-slate-700">
                  {dragging ? 'Drop it here' : 'Drop your PDF here'}
                </p>
                <p className="text-xs text-slate-400 mt-1">or click to browse</p>
              </div>
            )}
          </div>

          {/* Error message */}
          {error && (
            <div className="mx-6 mb-4 flex items-start gap-2.5 p-3 rounded-lg bg-red-50 border border-red-100">
              <svg className="w-4 h-4 text-red-500 flex-shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
              </svg>
              <p className="text-sm text-red-700">{error}</p>
            </div>
          )}

          {/* Action area */}
          <div className="px-6 pb-6">
            <button
              onClick={handleUpload}
              disabled={!selectedFile || uploading}
              className={`w-full py-3 px-4 rounded-xl font-semibold text-sm transition-all
                ${!selectedFile || uploading
                  ? 'bg-slate-100 text-slate-400 cursor-not-allowed'
                  : 'bg-indigo-600 text-white hover:bg-indigo-700 active:scale-[0.98] shadow-sm hover:shadow-indigo-200 hover:shadow-md'
                }`}
            >
              {uploading ? (
                <span className="flex items-center justify-center gap-2">
                  <svg className="animate-spin w-4 h-4" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                  </svg>
                  Uploading…
                </span>
              ) : 'Generate Anki Deck'}
            </button>

            <p className="mt-3 text-center text-xs text-slate-400">
              Processing typically takes 3–8 minutes depending on PDF size
            </p>
          </div>
        </div>

        {/* Footer */}
        <p className="mt-8 text-xs text-slate-400">
          Sign in to save your quiz history · Files auto-deleted after 7 days
        </p>
      </div>
    </>
  )
}
