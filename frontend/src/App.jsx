import { useState, useEffect } from 'react'
import UploadPanel       from './components/UploadPanel'
import ReviewPointsPanel from './components/ReviewPointsPanel'
import SummaryBar        from './components/SummaryBar'
import ResultsTable      from './components/ResultsTable'

const DEFAULT_RP = { rp1: true, rp2: true, rp3: true, rp4: true, rp5: true }

function ExportButton({ label, href, disabled, color }) {
  return (
    <a
      href={disabled ? undefined : href}
      className={`inline-flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-medium border transition-all
        ${disabled
          ? 'opacity-30 cursor-not-allowed border-border text-dim'
          : color === 'green'
            ? 'border-green-500/40 text-green-400 bg-green-500/10 hover:bg-green-500/20 cursor-pointer'
            : 'border-blue-500/40 text-blue-400 bg-blue-500/10 hover:bg-blue-500/20 cursor-pointer'
        }`}
      download
    >
      {label}
    </a>
  )
}

function ClaudeModal({ chunks, onOk }) {
  const [checked, setChecked] = useState(false)
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="bg-surface border border-border rounded-2xl shadow-2xl w-full max-w-sm mx-4 p-6">
        <p className="text-text text-sm font-semibold mb-3">
          {chunks} requirement(s) queued for Claude AI!
        </p>
        <p className="text-dim text-sm mb-1 font-medium">Steps:</p>
        <ol className="text-dim text-sm space-y-1 mb-5 list-decimal list-inside">
          <li>Open Claude Desktop</li>
          <li>Start a New Chat</li>
          <li>Press Ctrl+V to paste</li>
          <li>Press Enter</li>
        </ol>
        <p className="text-dim text-xs mb-5">
          Results will appear here automatically when Claude finishes.
        </p>
        <label className="flex items-center gap-2 cursor-pointer mb-5 select-none">
          <input
            type="checkbox"
            checked={checked}
            onChange={e => setChecked(e.target.checked)}
            className="w-4 h-4 accent-amber cursor-pointer"
          />
          <span className="text-dim text-sm">Don't ask me again</span>
        </label>
        <div className="flex justify-end">
          <button
            onClick={() => onOk(checked)}
            className="px-6 py-2 rounded-xl bg-blue-500 hover:bg-blue-400 text-white text-sm font-semibold transition-all"
          >
            OK
          </button>
        </div>
      </div>
    </div>
  )
}

export default function App() {
  const [uploadData,   setUploadData]   = useState(null)
  const [reviewPoints, setReviewPoints] = useState(DEFAULT_RP)
  const [generating,   setGenerating]   = useState(false)
  const [testCases,    setTestCases]    = useState([])
  const [summary,      setSummary]      = useState(null)
  const [error,        setError]        = useState('')
  const [progress,     setProgress]     = useState('')

  // ── MCP / Claude Desktop state ───────────────────────────────────────────
  const [mode,         setMode]         = useState({ mode: 'offline', engine: 'Rule-Based NLP' })
  const [mcpAvailable, setMcpAvailable] = useState(false)
  const [mcpResults,   setMcpResults]   = useState(null)
  const [aiWaiting,    setAiWaiting]    = useState(false)
  const [exportSource, setExportSource] = useState('session') // 'session' | 'mcp'

  // ── Claude AI instructions modal state ───────────────────────────────────
  const [showModal,    setShowModal]    = useState(false)
  const [modalChunks,  setModalChunks]  = useState(0)
  const [dontAskAgain, setDontAskAgain] = useState(() => localStorage.getItem('claudeModalDismissed') === 'true')

  // ── Fetch engine mode on startup ─────────────────────────────────────────
  useEffect(() => {
    fetch('/api/mode')
      .then(r => r.ok ? r.json() : null)
      .then(data => { if (data) setMode(data) })
      .catch(() => {})
  }, [])

  // ── Poll for Claude Desktop results every 3 seconds ──────────────────────
  useEffect(() => {
    const poll = setInterval(() => {
      fetch('/api/mcp/latest')
        .then(r => r.ok ? r.json() : null)
        .then(data => {
          if (data && data.available && data.test_cases?.length > 0) {
            setMcpAvailable(true)
            setMcpResults(data)
            setAiWaiting(false)
          }
        })
        .catch(() => {})
    }, 3000)
    return () => clearInterval(poll)
  }, [])

  const handleRpChange = (id, val) =>
    setReviewPoints(rp => ({ ...rp, [id]: val }))

  // ── Rule-based generation ─────────────────────────────────────────────────
  const handleGenerate = async () => {
    if (!uploadData?.session_id) return
    setGenerating(true)
    setError('')
    setTestCases([])
    setSummary(null)
    setProgress('Analysing document…')

    try {
      setProgress('Ingesting requirements…')
      const res = await fetch('/api/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id:            uploadData.session_id,
          review_points:         reviewPoints,
          icd_session_id:        uploadData.icd_session_id || null,
          supporting_session_id: uploadData.supporting_session_id || null,
        }),
      })
      const data = await res.json()
      if (!res.ok) {
        throw new Error(data?.detail?.error || data?.detail || 'Generation failed')
      }
      setProgress('Applying deduplication…')
      setTestCases(data.test_cases)
      setSummary(data.summary)
      setExportSource('session')
    } catch (e) {
      setError(e.message)
    } finally {
      setGenerating(false)
      setProgress('')
    }
  }

  // ── Claude AI generation (Claude Desktop via MCP) ────────────────────────
  // This handler is EXCLUSIVELY for the "Generate Test Cases using Claude AI"
  // button. It calls /api/generate/ai which queues requirement chunks for
  // Claude Desktop — the rule-based engine is never invoked here.
  const handleClaudeGenerate = async () => {
    if (!uploadData?.session_id) return
    setError('')
    setTestCases([])
    setSummary(null)

    try {
      // Queue the document for Claude AI via the dedicated AI endpoint
      const queueRes = await fetch('/api/generate/ai', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({
          session_id:            uploadData.session_id,
          icd_session_id:        uploadData.icd_session_id        || null,
          supporting_session_id: uploadData.supporting_session_id || null,
        }),
      })
      const queueData = await queueRes.json()
      if (!queueRes.ok) {
        setError(queueData?.detail?.suggestion || queueData?.detail || 'Failed to queue for Claude AI')
        return
      }

      const totalChunks = queueData.total_chunks ?? 0
      if (totalChunks === 0) {
        setError('No requirements found in the document.')
        return
      }

      // Build the Claude Desktop prompt — instructs Claude to generate test
      // cases from scratch using the NLP context returned by get_generated_test_cases.
      const prompt = [
        'Generate test cases for my SRS document using tc-tool.',
        '',
        'Follow these steps EXACTLY:',
        '',
        'STEP 1: Call tc-tool get_generated_test_cases',
        'This returns NLP-extracted context (sentences, subjects, actions,',
        'testing types, priorities, and methodologies) for each requirement.',
        'Use this context as your input — do NOT copy it as output.',
        '',
        'STEP 2: For each requirement in the context, generate test cases',
        'covering ALL FOUR scenario types: normal, boundary, edge, robustness.',
        'Author every field from scratch using the NLP context as your guide:',
        '  - traceability_req_id : use requirement_id from context exactly',
        '  - test_case_id        : TC_VD_001 (validation) / TC_IT_001 (integration) / TC_UT_001 (verification); one ID per requirement',
        '  - scenario_id         : SC_001, SC_002, SC_003, SC_004 — reset per requirement',
        '  - priority            : use scenario_priorities[scenario_type] from context',
        '  - module              : use module from context exactly',
        '  - requirement_type    : use requirement_type from context (functional or non-functional)',
        '  - scenario_type       : normal | boundary | edge | robustness',
        '  - testing_type        : use testing_type from context',
        '  - test_environment    : use test_environment from context',
        '  - design_methodology  : use scenario_methodologies[scenario_type] from context',
        '  - dependent_test_cases: "None" for SC_001; "TC_XX_NNN_SC-001" for all others',
        '  - inputs              : list of realistic test input values for the scenario',
        '  - objective           : clear, specific — no modal verbs (shall/must/can/will)',
        '  - preconditions       : list of specific, testable preconditions',
        '  - test_steps          : list of numbered actionable strings ["1. ...", "2. ..."]',
        '  - expected_outcome    : MUST start with "ActualSignalName = Value. " using the REAL',
        '                          output signal name from the requirement (e.g.',
        '                          "Altitude Alert Condition Enabled = True. System sets output.").',
        '                          normal/boundary → True/Enabled/Active.',
        '                          edge/robustness → False/Disabled/Inactive.',
        '                          NEVER write "Output signal", "output", or any generic placeholder.',
        '  - inputs              : list of strings in "SignalName: Value" format using the REAL',
        '                          signal names from the requirement (e.g. "Tail Low Condition: True")',
        '  - remarks             : risk, compliance, ambiguity, or coverage observations',
        '',
        'STEP 3: Call tc-tool save_enhanced_test_cases with the complete list.',
        '',
        'IMPORTANT RULES:',
        '  - No modal verbs anywhere in objective, test_steps, or expected_outcome',
        '  - test_steps must be an array of numbered strings: ["1. Do X", "2. Do Y"]',
        '  - preconditions must be an array of strings',
        '  - inputs must be an array of strings in "SignalName: Value" format',
        '  - expected_outcome must start with the real signal name, not a generic placeholder',
        '  - You MUST call save_enhanced_test_cases — do not just show results in chat',
        `Total requirements queued: ${totalChunks}`,
      ].join('\n')

      try {
        await navigator.clipboard.writeText(prompt)
      } catch {
        const ta = document.createElement('textarea')
        ta.value = prompt
        document.body.appendChild(ta)
        ta.select()
        document.execCommand('copy')
        document.body.removeChild(ta)
      }

      setAiWaiting(true)
      if (!localStorage.getItem('claudeModalDismissed')) {
        setModalChunks(totalChunks)
        setShowModal(true)
      }
    } catch (e) {
      setError('Failed to queue for Claude AI: ' + e.message)
    }
  }

  const handleRemindClaude = () => {
    const msg = [
      'IMPORTANT: You must call tc-tool save_enhanced_test_cases NOW.',
      '',
      'Pass the complete list of ALL test cases you generated,',
      'with every field populated as instructed.',
      '',
      'The React UI at localhost:5173 is waiting for save_enhanced_test_cases.',
      'Do NOT just show results in chat — you must call the tool.',
    ].join('\n')

    navigator.clipboard.writeText(msg).catch(() => {
      const ta = document.createElement('textarea')
      ta.value = msg
      document.body.appendChild(ta)
      ta.select()
      document.execCommand('copy')
      document.body.removeChild(ta)
    })
    alert('Reminder copied — paste into Claude Desktop and press Enter.')
  }

  const handleLoadMcpResults = () => {
    if (!mcpResults) return
    setTestCases(mcpResults.test_cases)
    setSummary(mcpResults.summary)
    setMcpAvailable(false)
    setExportSource('mcp')
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  const handleModalOk = (checked) => {
    if (checked) localStorage.setItem('claudeModalDismissed', 'true')
    setShowModal(false)
  }

  const sessionId = uploadData?.session_id
  const isMcp     = mode?.mode === 'online'

  return (
    <div className="min-h-screen bg-bg text-text font-sans">

      {/* Claude AI Instructions Modal */}
      {showModal && (
        <ClaudeModal
          chunks={modalChunks}
          onOk={handleModalOk}
        />
      )}

      {/* Header */}
      <header className="border-b border-border bg-surface sticky top-0 z-50">
        <div className="max-w-screen-2xl mx-auto px-6 h-14 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-amber/10 border border-amber/30 flex items-center justify-center">
              <span className="text-amber text-sm">⚙</span>
            </div>
            <div>
              <h1 className="text-sm font-semibold text-text leading-none">Test Case Generator</h1>
              <p className="text-[10px] text-dim font-mono">Rule-Based NLP · No API · No LLM</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <span className={`w-2 h-2 rounded-full inline-block ${isMcp ? 'bg-green-400' : 'bg-amber-400'}`} />
            <span className="text-xs text-dim font-mono">
              {isMcp ? 'AI Mode — Claude Desktop' : 'Offline Mode — Rule-Based'}
            </span>
          </div>
        </div>
      </header>

      <div className="max-w-screen-2xl mx-auto px-6 py-8 space-y-8">

        {/* Claude Desktop Results Banner */}
        {mcpAvailable && mcpResults && (
          <div className="bg-card border border-amber/40 rounded-2xl p-5 flex items-center justify-between flex-wrap gap-4">
            <div className="flex items-center gap-3">
              <span className="text-amber text-xl">✦</span>
              <div>
                <p className="text-sm font-semibold text-text">Claude Desktop Results Ready</p>
                <p className="text-xs text-dim mt-0.5">
                  {mcpResults.timestamp} · {mcpResults.summary?.total ?? mcpResults.test_cases?.length} test cases generated
                </p>
              </div>
            </div>
            <div className="flex flex-wrap gap-3">
              <button
                onClick={handleLoadMcpResults}
                className="px-4 py-2 rounded-xl text-sm font-semibold bg-amber text-bg hover:bg-amber/90 transition-all"
              >
                Load Results
              </button>
              <a href="/api/export/excel/mcp" download
                className="px-4 py-2 rounded-xl text-sm font-medium border border-green-500/40 text-green-400 bg-green-500/10 hover:bg-green-500/20 transition-all">
                📥 Download Excel
              </a>
              <a href="/api/export/docx/mcp" download
                className="px-4 py-2 rounded-xl text-sm font-medium border border-blue-500/40 text-blue-400 bg-blue-500/10 hover:bg-blue-500/20 transition-all">
                📄 Download Word
              </a>
            </div>
          </div>
        )}

        {/* Top grid: upload + review points + generate */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">

          {/* Upload */}
          <div className="bg-card border border-border rounded-2xl p-6">
            <UploadPanel onUploaded={setUploadData} />
          </div>

          {/* Review points + generate */}
          <div className="bg-card border border-border rounded-2xl p-6 flex flex-col gap-6">
            <ReviewPointsPanel
              reviewPoints={reviewPoints}
              onChange={handleRpChange}
              disabled={generating}
            />

            {/* Step 3 — Generate */}
            <div>
              <div className="flex items-center gap-3 mb-4">
                <div className="w-7 h-7 rounded bg-amber/10 border border-amber/30 flex items-center justify-center text-amber text-sm font-mono font-bold">3</div>
                <h2 className="text-base font-semibold text-text">Generate</h2>
              </div>

              {/* Rule-based button */}
              <button
                onClick={handleGenerate}
                disabled={!uploadData || generating}
                className={`w-full py-3 rounded-xl font-semibold text-sm transition-all flex items-center justify-center gap-2
                  ${!uploadData || generating
                    ? 'bg-border text-muted cursor-not-allowed'
                    : 'bg-amber hover:bg-amber2 text-bg cursor-pointer shadow-lg shadow-amber/20'
                  }`}
              >
                {generating ? (
                  <>
                    <div className="w-4 h-4 border-2 border-bg border-t-transparent rounded-full spin" />
                    {progress || 'Generating…'}
                  </>
                ) : (
                  <>⚙ Generate Test Cases</>
                )}
              </button>

              {/* Claude AI button */}
              {uploadData && !generating && (
                <button
                  onClick={handleClaudeGenerate}
                  className="w-full py-2.5 rounded-xl text-sm font-medium border border-amber/30 text-amber hover:bg-amber/10 transition-all mt-2 flex items-center justify-center gap-2"
                >
                  <span>✦</span>
                  <span>Generate with Claude AI</span>
                </button>
              )}

              {/* Waiting for Claude spinner */}
              {aiWaiting && (
                <div className="mt-3 rounded-xl bg-amber/5 border border-amber/20 overflow-hidden">
                  <div className="px-4 py-3 flex items-center gap-3">
                    <div className="w-4 h-4 border-2 border-amber border-t-transparent rounded-full spin flex-shrink-0" />
                    <div>
                      <p className="text-sm text-amber font-medium">Waiting for Claude AI…</p>
                      <p className="text-xs text-dim mt-0.5">
                        Paste the prompt into Claude Desktop and press Enter.
                        Results appear here automatically.
                      </p>
                    </div>
                  </div>
                  <div className="border-t border-amber/10 px-4 py-2">
                    <button
                      onClick={handleRemindClaude}
                      className="text-xs text-dim hover:text-amber transition-colors"
                    >
                      Claude showed results in chat but UI not updated? Click here →
                    </button>
                  </div>
                </div>
              )}

              {!uploadData && (
                <p className="text-center text-xs text-muted mt-2">Upload a document first</p>
              )}

              {error && (
                <div className="mt-3 px-4 py-2.5 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400 text-sm">
                  ⚠ {error}
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Summary */}
        {summary && (
          <div className="bg-card border border-border rounded-2xl p-6">
            <SummaryBar summary={summary} />
          </div>
        )}

        {/* Export buttons */}
        {testCases.length > 0 && (
          <div className="bg-card border border-border rounded-2xl p-6">
            <div className="flex items-center gap-3 mb-4">
              <div className="w-7 h-7 rounded bg-amber/10 border border-amber/30 flex items-center justify-center text-amber text-sm font-mono font-bold">5</div>
              <h2 className="text-base font-semibold text-text">Export</h2>
            </div>
            <div className="flex flex-wrap gap-3">
              <ExportButton
                label="📥 Download Excel (.xlsx)"
                href={exportSource === 'mcp' ? '/api/export/excel/mcp' : `/api/export/excel?session_id=${sessionId}`}
                disabled={exportSource === 'session' && !sessionId}
                color="green"
              />
              <ExportButton
                label="📄 Download Word (.docx)"
                href={exportSource === 'mcp' ? '/api/export/docx/mcp' : `/api/export/docx?session_id=${sessionId}`}
                disabled={exportSource === 'session' && !sessionId}
                color="blue"
              />
            </div>
            <p className="text-xs text-dim mt-2">
              {exportSource === 'mcp' ? '✦ Exporting Claude AI results' : '⚙ Exporting rule-based results'}
            </p>
          </div>
        )}

        {/* Results table */}
        {testCases.length > 0 && (
          <div className="bg-card border border-border rounded-2xl p-6">
            <ResultsTable testCases={testCases} />
          </div>
        )}

      </div>
    </div>
  )
}
