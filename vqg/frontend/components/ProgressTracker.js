/**
 * ProgressTracker — Visual pipeline stage stepper.
 *
 * Props:
 *   status        — current JobStatus string
 *   totalImages   — integer
 *   processedImages — integer
 *   quizCount     — integer
 */

const STAGES = [
  { key: 'QUEUED',      label: 'Queued',                      sub: 'Waiting to start' },
  { key: 'PARSING',     label: 'Extracting images',           sub: 'Reading PDF pages' },
  { key: 'TRIAGING',    label: 'Classifying images',          sub: 'Identifying quiz-worthy diagrams' },
  { key: 'PROCESSING',  label: 'Numbering structures',        sub: 'Replacing labels with numbers' },
  { key: 'GENERATING',  label: 'Generating questions',        sub: 'Building MCQ distractors' },
  { key: 'EXPORTING',   label: 'Building Anki deck',          sub: 'Packaging .apkg file' },
  { key: 'COMPLETE',    label: 'Complete',                    sub: 'Your deck is ready' },
]

const STAGE_ORDER = STAGES.map((s) => s.key)

function getStageIndex(status) {
  const idx = STAGE_ORDER.indexOf(status)
  return idx === -1 ? 0 : idx
}

export default function ProgressTracker({ status, totalImages, processedImages, generatedImages, quizCount }) {
  const failed = status === 'FAILED'
  const currentIdx = failed ? -1 : getStageIndex(status)

  const processedPct =
    totalImages > 0 ? Math.round((processedImages / totalImages) * 100) : 0
  const generatedPct =
    totalImages > 0 ? Math.round((generatedImages / totalImages) * 100) : 0

  return (
    <div>
      {/* Stage stepper */}
      <ol className="space-y-0">
        {STAGES.map((stage, idx) => {
          const isComplete = !failed && idx < currentIdx
          const isActive   = !failed && idx === currentIdx
          const isFailed   = failed && idx === currentIdx
          const isPending  = !isComplete && !isActive && !isFailed

          return (
            <li key={stage.key} className="flex gap-4">
              {/* Left column: circle + connector line */}
              <div className="flex flex-col items-center">
                {/* Circle */}
                <div className={`relative flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center transition-all
                  ${isComplete ? 'bg-indigo-600'
                    : isActive  ? 'bg-indigo-600 ring-4 ring-indigo-100'
                    : isFailed  ? 'bg-red-500'
                    : 'bg-white border-2 border-slate-200'
                  }`}
                >
                  {isComplete && (
                    <svg className="w-4 h-4 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
                    </svg>
                  )}
                  {isActive && (
                    <span className="w-2.5 h-2.5 bg-white rounded-full animate-pulse" />
                  )}
                  {isFailed && (
                    <svg className="w-4 h-4 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                    </svg>
                  )}
                  {isPending && (
                    <span className="w-2 h-2 bg-slate-300 rounded-full" />
                  )}
                </div>

                {/* Connector line — don't render after last item */}
                {idx < STAGES.length - 1 && (
                  <div className={`w-0.5 flex-1 my-1 transition-colors ${isComplete ? 'bg-indigo-300' : 'bg-slate-200'}`} />
                )}
              </div>

              {/* Right column: text */}
              <div className={`pb-6 ${idx === STAGES.length - 1 ? 'pb-0' : ''}`}>
                <p className={`text-sm font-semibold leading-8
                  ${isComplete || isActive ? 'text-slate-900' : 'text-slate-400'}
                  ${isFailed ? 'text-red-600' : ''}
                `}>
                  {stage.label}
                </p>
                {(isActive || isFailed) && (
                  <p className={`text-xs mt-0 -mt-1 ${isFailed ? 'text-red-500' : 'text-indigo-500'}`}>
                    {isFailed ? 'Something went wrong' : stage.sub}
                  </p>
                )}
              </div>
            </li>
          )
        })}
      </ol>

      {/* Progress bars — shown once we know total */}
      {totalImages > 0 && !failed && (
        <div className="mt-6 pt-6 border-t border-slate-100 space-y-4">

          {/* Numbering progress — shown during PROCESSING and beyond */}
          {processedImages > 0 && (
            <div>
              <div className="flex justify-between items-center mb-1.5">
                <span className="text-xs font-medium text-slate-500">Images numbered</span>
                <span className="text-xs font-semibold text-slate-700">
                  {processedImages} / {totalImages}
                </span>
              </div>
              <div className="w-full bg-slate-100 rounded-full h-1.5 overflow-hidden">
                <div
                  className="bg-indigo-500 h-1.5 rounded-full transition-all duration-500"
                  style={{ width: `${processedPct}%` }}
                />
              </div>
            </div>
          )}

          {/* Generating progress — shown during GENERATING and beyond */}
          {(generatedImages > 0 || status === 'GENERATING') && (
            <div>
              <div className="flex justify-between items-center mb-1.5">
                <span className="text-xs font-medium text-slate-500">Questions generated</span>
                <span className="text-xs font-semibold text-slate-700">
                  {generatedImages} / {totalImages}
                  {quizCount > 0 && (
                    <span className="ml-2 text-slate-400 font-normal">
                      ({quizCount} question{quizCount !== 1 ? 's' : ''})
                    </span>
                  )}
                </span>
              </div>
              <div className="w-full bg-slate-100 rounded-full h-1.5 overflow-hidden">
                <div
                  className="bg-emerald-500 h-1.5 rounded-full transition-all duration-500"
                  style={{ width: `${generatedPct}%` }}
                />
              </div>
            </div>
          )}

        </div>
      )}
    </div>
  )
}
