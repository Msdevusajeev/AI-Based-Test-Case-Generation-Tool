import { useState, useEffect, useRef, useCallback } from 'react'
import ReviewPointsPanel from './components/ReviewPointsPanel'
import ResultsTable      from './components/TCTable'
import ScopeSelector     from './components/ScopeSelector'

const DEFAULT_RP = { rp1: true, rp2: true, rp3: true, rp4: true, rp5: true }
const ACCEPTED   = ['.pdf', '.docx', '.xlsx']

// ─── tiny helpers ─────────────────────────────────────────────────────────────

function formatBytes(n) {
  if (!n) return ''
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / (1024 * 1024)).toFixed(2)} MB`
}

// ─── Upload drop-zone ─────────────────────────────────────────────────────────

function DropZone({ label, required, file, loading, error, onFile, onClear }) {
  const [drag, setDrag] = useState(false)
  const ref = useRef()
  const ext = file?.name?.split('.').pop()?.toLowerCase()

  const onDrop = useCallback(e => {
    e.preventDefault(); setDrag(false); onFile(e.dataTransfer.files[0])
  }, [onFile])

  return (
    <div
      className={`rounded-xl border-2 border-dashed transition-all cursor-pointer select-none
        ${drag           ? 'border-amber bg-amber/5'
        : file           ? 'border-green-500/40 bg-green-500/5'
        : error          ? 'border-red-500/40 bg-red-500/5'
        :                  'border-border hover:border-amber/40 bg-card'}`}
      onClick={() => !file && ref.current.click()}
      onDragOver={e => { e.preventDefault(); setDrag(true) }}
      onDragLeave={() => setDrag(false)}
      onDrop={onDrop}
    >
      <input ref={ref} type="file" accept=".pdf,.docx,.xlsx" className="hidden"
        onChange={e => onFile(e.target.files[0])} />

      <div className="p-6">
        {loading ? (
          <div className="flex flex-col items-center gap-3">
            <div className="w-8 h-8 border-2 border-amber border-t-transparent rounded-full spin" />
            <p className="text-sm text-dim">Uploading…</p>
          </div>
        ) : file ? (
          <div className="flex items-center gap-4">
            <div className="w-12 h-12 rounded-xl bg-green-500/10 border border-green-500/30 flex items-center justify-center text-2xl flex-shrink-0">
              {ext === 'pdf' ? '📄' : ext === 'docx' || ext === 'doc' ? '📝' : '📊'}
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium text-text truncate">{file.name}</p>
              <p className="text-xs text-dim font-mono mt-0.5">{formatBytes(file.size)}</p>
              <span className="text-xs text-green-400 mt-0.5 block">✓ Uploaded successfully</span>
            </div>
            <button onClick={e => { e.stopPropagation(); onClear() }}
              className="flex-shrink-0 text-dim hover:text-red-400 transition-colors text-sm px-2 py-1 rounded-lg hover:bg-red-500/10">
              ✕ Remove
            </button>
          </div>
        ) : (
          <div className="flex items-center gap-4">
            <div className="w-12 h-12 rounded-xl border border-border bg-surface flex items-center justify-center text-2xl flex-shrink-0">
              📋
            </div>
            <div>
              <p className="text-sm text-text font-medium">
                Drop {label} here or <span className="text-amber underline">Click to browse</span>
              </p>
              <div className="flex items-center gap-2 mt-1.5">
                {ACCEPTED.map(e => (
                  <span key={e} className="px-1.5 py-0.5 rounded text-[10px] font-mono bg-border text-dim">{e}</span>
                ))}
                {required && <span className="text-[10px] text-amber/80 font-medium">mandatory</span>}
              </div>
            </div>
          </div>
        )}
      </div>
      {error && (
        <div className="px-4 pb-3">
          <p className="text-xs text-red-400">⚠ {error}</p>
        </div>
      )}
    </div>
  )
}

// ─── Page: Upload ─────────────────────────────────────────────────────────────

function PageUpload({ files, loading, errors, onFile, onClear, onNext, reqPrefixes, onReqPrefixesChange }) {
  const srsReady    = !!files.srs
  // REQ prefix is valid only if it resolves to at least one non-empty token
  const prefixReady = reqPrefixes.split(',').map(p => p.trim()).filter(Boolean).length > 0
  const canProceed  = srsReady && prefixReady
  return (
    <div className="max-w-3xl mx-auto px-6 py-8">
      <div className="mb-8">
        <h2 className="text-xl font-semibold text-text">Upload Requirements</h2>
        <p className="text-sm text-dim mt-1">Start with your SRS document. ICD and supporting docs are optional but improve coverage.</p>
      </div>

      <div className="space-y-5">
        {/* SRS */}
        <div>
          <div className="flex items-center gap-2 mb-2">
            <span className="px-2 py-0.5 rounded text-xs font-mono font-bold bg-amber/15 text-amber border border-amber/30">SRS</span>
            <span className="text-sm text-text font-medium">Software Requirements Specification</span>
            <span className="text-xs text-red-400/80 ml-1">* Mandatory</span>
          </div>
          <DropZone label="SRS document" required
            file={files.srs} loading={loading.srs} error={errors.srs}
            onFile={f => onFile('srs', f)} onClear={() => onClear('srs')} />
        </div>

        {/* Requirement ID Prefix */}
        <div>
          <div className="flex items-center gap-2 mb-2">
            <span className="px-2 py-0.5 rounded text-xs font-mono font-bold bg-amber/15 text-amber border border-amber/30">REQ</span>
            <span className="text-sm text-text font-medium">Requirement ID Prefix</span>
            <span className="text-xs text-red-400/80 ml-1">* Mandatory</span>
            <div className="relative group cursor-help ml-1">
              <span className="text-dim/50 text-xs select-none">ⓘ</span>
              <div className="absolute left-0 top-5 z-50 hidden group-hover:block w-72 bg-surface border border-border rounded-lg px-3 py-2 text-xs text-dim shadow-xl">
                Only IDs that start with this prefix are treated as requirements.
                Stops table labels, figure numbers, and ICD signal names from being picked up.
                <span className="text-amber/80 block mt-1">e.g. <code className="font-mono text-amber">MRJ_MCU_SRS_</code> or <code className="font-mono text-amber">REQ_</code></span>
                <span className="text-dim/60 block mt-0.5">Comma-separate for multiple prefixes.</span>
              </div>
            </div>
          </div>
          <input
            type="text"
            value={reqPrefixes}
            onChange={e => onReqPrefixesChange(e.target.value)}
            placeholder="e.g.  MRJ_MCU_SRS_    or    REQ_, SYS_REQ_"
            className="w-full bg-card border border-border rounded-xl px-4 py-3 text-sm text-text font-mono placeholder:text-dim/40 focus:outline-none focus:border-amber/60 transition-colors"
          />
          {reqPrefixes.trim() && (
            <div className="flex flex-wrap gap-1.5 mt-2">
              {reqPrefixes.split(',').map(p => p.trim()).filter(Boolean).map((p, i) => (
                <span key={i} className="px-2.5 py-0.5 rounded-full text-xs font-mono bg-amber/10 text-amber border border-amber/25">
                  {p}
                </span>
              ))}
            </div>
          )}
        </div>

        {/* ICD */}
        <div>
          <div className="flex items-center gap-2 mb-2">
            <span className="px-2 py-0.5 rounded text-xs font-mono font-bold bg-border text-dim">ICD</span>
            <span className="text-sm text-text font-medium">Interface Control Document</span>
            <span className="text-xs text-dim ml-1">optional</span>
          </div>
          <DropZone label="ICD document"
            file={files.icd} loading={loading.icd} error={errors.icd}
            onFile={f => onFile('icd', f)} onClear={() => onClear('icd')} />
        </div>

        {/* Supporting */}
        <div>
          <div className="flex items-center gap-2 mb-2">
            <span className="px-2 py-0.5 rounded text-xs font-mono font-bold bg-border text-dim">SUP</span>
            <div className="relative group flex items-center gap-1">
              <span className="text-sm text-text font-medium">Supporting Document</span>
              <span className="text-dim/50 text-xs cursor-help">ⓘ</span>
              <div className="absolute left-0 top-6 z-50 hidden group-hover:block bg-surface border border-border rounded-lg px-3 py-2 text-xs text-dim shadow-lg whitespace-nowrap">
                System document — ICD, test plans, or any reference material
              </div>
            </div>
            <span className="text-xs text-dim ml-1">optional</span>
          </div>
          {/* Multi supporting documents */}
          <div className="space-y-2">
            {(files.supportingList || []).map((f, idx) => (
              <div key={idx} className="flex items-center gap-3 px-4 py-2.5 rounded-xl border border-green-500/30 bg-green-500/5">
                <span className="text-xl">{f.name?.endsWith('.pdf') ? '📄' : f.name?.endsWith('.docx') ? '📝' : '📊'}</span>
                <div className="flex-1 min-w-0">
                  <p className="text-sm text-text truncate">{f.name}</p>
                  <p className="text-xs text-green-400">✓ Uploaded</p>
                </div>
                <button onClick={() => onClear('supporting', idx)}
                  className="text-dim hover:text-red-400 transition-colors text-xs px-2 py-1 rounded hover:bg-red-500/10">
                  ✕
                </button>
              </div>
            ))}
            <div
              className="rounded-xl border-2 border-dashed border-border hover:border-amber/40 bg-card transition-all cursor-pointer"
              onClick={() => document.getElementById('sup-input').click()}
              onDragOver={e => e.preventDefault()}
              onDrop={e => { e.preventDefault(); Array.from(e.dataTransfer.files).forEach(f => onFile('supporting', f)) }}
            >
              <input id="sup-input" type="file" accept=".pdf,.docx,.xlsx" multiple className="hidden"
                onClick={e => { e.target.value = '' }}
              onChange={e => Array.from(e.target.files).forEach(f => onFile('supporting', f))} />
              <div className="p-4 flex items-center gap-4">
                <div className="w-10 h-10 rounded-xl border border-border bg-surface flex items-center justify-center text-xl flex-shrink-0">📋</div>
                <div>
                  <p className="text-sm text-text font-medium">
                    {(files.supportingList||[]).length > 0 ? 'Add another document' : 'Drop supporting documents here or'}&nbsp;
                    <span className="text-amber underline">Click to browse</span>
                  </p>
                  <div className="flex items-center gap-2 mt-1">
                    <span className="px-1.5 py-0.5 rounded text-[10px] font-mono bg-border text-dim">.pdf</span>
                    <span className="px-1.5 py-0.5 rounded text-[10px] font-mono bg-border text-dim">.docx</span>
                    <span className="px-1.5 py-0.5 rounded text-[10px] font-mono bg-border text-dim">.xlsx</span>
                    <span className="text-[10px] text-dim/60 ml-1">Multiple files supported</span>
                  </div>
                </div>
              </div>
              {errors.supporting && <p className="px-4 pb-3 text-xs text-red-400">⚠ {errors.supporting}</p>}
            </div>
          </div>
        </div>
      </div>

      <div className="mt-8 flex justify-end">
        <button onClick={onNext} disabled={!canProceed}
          title={!canProceed ? 'Upload an SRS document and enter a Requirement ID prefix to continue' : ''}
          className={`px-6 py-2.5 rounded-xl text-sm font-semibold transition-all flex items-center gap-2
            ${canProceed
              ? 'bg-amber hover:bg-amber/90 text-bg shadow-sm shadow-amber/20 cursor-pointer'
              : 'bg-border text-dim cursor-not-allowed'}`}>
          Next: Configure →
        </button>
      </div>
    </div>
  )
}

// ─── Page: Configure ──────────────────────────────────────────────────────────

function PageConfigure({ sessionId, scopeConfig, onScopeChange, reviewPoints, onRpChange, customReviewPoints, onCustomReviewPointsChange, generating, onBack, onGenerate, onNext, reqPrefixes }) {
  return (
    <div className="max-w-5xl mx-auto px-6 py-8">
      <div className="mb-8">
        <h2 className="text-xl font-semibold text-text">Configure Generation</h2>
        <p className="text-sm text-dim mt-1">Select which requirements to target and choose your review points.</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">

        {/* Scope */}
        <div className="bg-card border border-border rounded-2xl p-5">
          <div className="flex items-center gap-2 mb-4">
            <div className="w-6 h-6 rounded-lg bg-amber/10 border border-amber/30 flex items-center justify-center text-amber text-xs">🎯</div>
            <h3 className="text-sm font-semibold text-text">Scope</h3>
            <span className="text-xs text-dim ml-1">— Choose which requirements to generate test cases for</span>
          </div>
          <ScopeSelector sessionId={sessionId} onChange={onScopeChange} reqPrefixes={reqPrefixes} />
        </div>

        {/* Review points */}
        <div className="bg-card border border-border rounded-2xl p-5">
          <div className="flex items-center gap-2 mb-4">
            <div className="w-6 h-6 rounded-lg bg-amber/10 border border-amber/30 flex items-center justify-center text-amber text-xs">☑</div>
            <h3 className="text-sm font-semibold text-text">Generation Checklists</h3>
          </div>
          <ReviewPointsPanel
            reviewPoints={reviewPoints}
            onChange={onRpChange}
            disabled={generating}
            customPoints={customReviewPoints}
            onCustomPointsChange={onCustomReviewPointsChange}
          />
        </div>
      </div>

      <div className="mt-8 flex items-center justify-between">
        <button onClick={onBack}
          className="px-5 py-2.5 rounded-xl text-sm border border-border text-dim hover:border-amber/40 hover:text-text transition-all">
          ← Back to Upload
        </button>
        <button onClick={onNext}
          className="px-7 py-2.5 rounded-xl text-sm font-semibold bg-amber hover:bg-amber/90 text-bg shadow-sm shadow-amber/20 cursor-pointer transition-all flex items-center gap-2">
          Next: Generate →
        </button>
      </div>
    </div>
  )
}

// ─── Page: Generate ───────────────────────────────────────────────────────────

function TokenUsageWidget({ aiWaiting }) {
  const [usage, setUsage] = useState(null)

  useEffect(() => {
    let alive = true
    const poll = () => {
      fetch('/api/tokens/usage')
        .then(r => r.ok ? r.json() : null)
        .then(d => { if (alive && d) setUsage(d) })
        .catch(() => {})
    }
    poll()
    const id = setInterval(poll, 3000)
    return () => { alive = false; clearInterval(id) }
  }, [aiWaiting])

  if (!usage || usage.calls_made === 0) return null

  const pct = usage.percent_used ?? 0
  const barColor = pct > 85 ? 'bg-red-500' : pct > 60 ? 'bg-amber' : 'bg-green-500'

  return (
    <div className="flex items-center gap-3 text-[11px] px-3 py-1.5 rounded-lg bg-card border border-border">
      <span className="text-dim">
        ⚡ <strong className="text-text">~{usage.total_tokens_est.toLocaleString()}</strong> tokens used by this generation
        <span className="text-dim/60"> (input ~{usage.input_tokens_est.toLocaleString()} / output ~{usage.output_tokens_est.toLocaleString()})</span>
      </span>
      <div className="flex items-center gap-1.5">
        <div className="w-20 h-1.5 rounded-full bg-border overflow-hidden">
          <div className={`h-full ${barColor} transition-all`} style={{ width: `${Math.min(100, pct)}%` }} />
        </div>
        <span className="text-dim" title="Estimate based only on tc-tool's own MCP calls — does not include other messages in this Claude Desktop chat">{pct}% of a fresh 200K window</span>
      </div>
    </div>
  )
}

function PageGenerate({
  testCases, summary, generating, progress, error, aiWaiting,
  uploadDone, onGenerate, onClaudeGenerate, onRemindClaude,
  onLoadMcp, mcpAvailable, mcpResults, onExport,
}) {
  const dupCount = summary?.duplicates_removed ?? 0
  const [showPreview,  setShowPreview]  = useState(true)
  const [showRegenerate, setShowRegenerate] = useState(false)
  return (
    <div className="flex flex-col h-full">

      {/* Toolbar */}
      <div className="flex-shrink-0 border-b border-border bg-surface px-6 py-3 flex items-center gap-3">
        <div className="flex gap-2 flex-1 flex-wrap">
          {summary ? (
            <>
              <span className="text-[11px] px-2 py-1 rounded-lg bg-card border border-border text-dim">
                <strong className="text-text">{summary.total}</strong> test cases
              </span>
              <span className="text-[11px] px-2 py-1 rounded-lg bg-card border border-border text-dim">
                <strong className="text-text">{Object.keys(summary.by_module || {}).length}</strong> modules
              </span>
              {dupCount > 0 && (
                <span className="text-[11px] px-2 py-1 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400">
                  ⊘ <strong>{dupCount}</strong> duplicates removed
                </span>
              )}
              <span className="text-[11px] px-2 py-1 rounded-lg bg-green-500/10 border border-green-500/30 text-green-400">
                ✓ full coverage
              </span>
              <TokenUsageWidget aiWaiting={aiWaiting} />
            </>
          ) : error ? (
            <span className="text-xs text-red-400">⚠ {error}</span>
          ) : (
            <div className="flex items-center gap-3">
              <span className="text-xs text-dim">{generating ? (progress || 'Generating…') : 'Click Generate to start'}</span>
              {aiWaiting && <TokenUsageWidget aiWaiting={aiWaiting} />}
            </div>
          )}
        </div>

        {/* Toolbar right buttons — only when test cases exist */}
        {testCases.length > 0 && (
          <div className="flex items-center gap-2 flex-shrink-0">
            <button
              onClick={() => setShowPreview(v => !v)}
              className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border border-border text-dim hover:border-amber/40 hover:text-amber transition-all"
            >
              {showPreview ? '🙈 Hide Preview' : '👁 Show Preview'}
            </button>
            <button
              onClick={() => setShowRegenerate(v => !v)}
              className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border border-amber/40 text-amber hover:bg-amber/10 transition-all"
            >
              ↺ Regenerate
            </button>
          </div>
        )}

      </div>

      {/* Regenerate panel */}
      {showRegenerate && testCases.length > 0 && (
        <div className="flex-shrink-0 mx-6 mt-3 px-5 py-4 rounded-xl bg-surface border border-border">
          <div className="flex items-center justify-between mb-3">
            <p className="text-xs font-semibold text-text">Generate again with a different engine</p>
            <button onClick={() => setShowRegenerate(false)} className="text-dim hover:text-text text-xs">✕</button>
          </div>
          <div className="flex gap-3">
            <button onClick={() => { onGenerate(); setShowRegenerate(false) }}
              className="flex-1 flex items-center gap-2 px-4 py-2.5 rounded-xl border border-amber/30 bg-amber/5 hover:bg-amber/10 hover:border-amber transition-all text-left">
              <span className="text-xl">⚙</span>
              <div>
                <p className="text-xs font-semibold text-text">Rule-Based NLP</p>
                <p className="text-[10px] text-dim">Instant · offline · deterministic</p>
              </div>
            </button>
            <button onClick={() => { onClaudeGenerate(); setShowRegenerate(false) }}
              className="flex-1 flex items-center gap-2 px-4 py-2.5 rounded-xl border border-amber/30 bg-amber/5 hover:bg-amber/10 hover:border-amber transition-all text-left">
              <span className="text-xl">✦</span>
              <div>
                <p className="text-xs font-semibold text-text">Claude AI</p>
                <p className="text-[10px] text-dim">Richer · context-aware · via Claude Desktop</p>
              </div>
            </button>
          </div>
        </div>
      )}

      {/* MCP banner */}
      {mcpAvailable && mcpResults && (
        <div className="flex-shrink-0 mx-6 mt-3 px-4 py-2.5 rounded-xl bg-amber/10 border border-amber/30 flex items-center gap-3">
          <span className="text-amber">✦</span>
          <div className="flex-1">
            <p className="text-xs font-medium text-amber">Claude AI results ready</p>
            <p className="text-[10px] text-dim">{mcpResults.summary?.total ?? mcpResults.test_cases?.length} test cases generated</p>
          </div>
          <button onClick={onLoadMcp}
            className="text-xs px-3 py-1.5 rounded-lg bg-amber text-bg font-semibold hover:bg-amber/90 transition-all">
            Load Results
          </button>
        </div>
      )}

      {/* AI waiting */}
      {aiWaiting && (
        <div className="flex-shrink-0 mx-6 mt-3 px-4 py-3 rounded-xl bg-amber/5 border border-amber/20 flex items-center gap-3">
          <div className="w-4 h-4 border-2 border-amber border-t-transparent rounded-full spin flex-shrink-0" />
          <div className="flex-1">
            <p className="text-xs text-amber font-medium">Waiting for Claude AI…</p>
            <p className="text-[10px] text-dim">Paste the prompt into Claude Desktop and press Enter. Results appear here automatically.</p>
          </div>
          <button onClick={onRemindClaude}
            className="text-[10px] text-dim hover:text-amber transition-colors underline flex-shrink-0">
            Copy reminder →
          </button>
        </div>
      )}

      {/* Table or empty */}
      {testCases.length > 0 ? (
        showPreview ? (
          <div className="flex-1 overflow-auto px-6 py-4">
            <ResultsTable testCases={testCases} />
          </div>
        ) : (
          <div className="flex-1 flex flex-col items-center justify-center gap-3 text-center">
            <span className="text-4xl">🙈</span>
            <p className="text-sm text-dim">Preview hidden</p>
            <button onClick={() => setShowPreview(true)}
              className="text-xs text-amber underline hover:no-underline">
              Show preview
            </button>
          </div>
        )
      ) : generating ? (
        <div className="flex-1 flex flex-col items-center justify-center gap-4 text-center">
          <div className="w-14 h-14 rounded-2xl bg-amber/10 border border-amber/30 flex items-center justify-center">
            <div className="w-7 h-7 border-2 border-amber border-t-transparent rounded-full spin" />
          </div>
          <div>
            <p className="text-sm font-medium text-amber">{progress || 'Generating test cases…'}</p>
            <p className="text-xs text-dim mt-1">This usually takes a few seconds</p>
          </div>
        </div>
      ) : error ? (
        <div className="flex-1 flex flex-col items-center justify-center gap-4 text-center">
          <div className="w-14 h-14 rounded-2xl bg-red-500/10 border border-red-500/30 flex items-center justify-center text-2xl">⚠</div>
          <div>
            <p className="text-sm font-medium text-red-400">Generation failed</p>
            <p className="text-xs text-dim mt-1 max-w-xs">{error}</p>
            <button onClick={onGenerate}
              className="mt-3 px-4 py-2 rounded-lg bg-amber text-bg text-xs font-semibold hover:bg-amber/90 transition-all">
              Try again
            </button>
          </div>
        </div>
      ) : (
        /* ── Engine selection ── */
        <div className="flex-1 flex flex-col items-center justify-center px-8 py-12">
          <p className="text-base font-semibold text-text mb-2">Choose generation engine</p>
          <p className="text-xs text-dim mb-8 text-center max-w-sm">
            Rule-Based runs instantly offline. Claude AI produces richer, context-aware test cases using Claude Desktop.
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-5 w-full max-w-2xl">

            {/* Rule-Based card */}
            <button onClick={onGenerate}
              className="group text-left p-6 rounded-2xl border-2 border-amber/30 bg-amber/5 hover:border-amber hover:bg-amber/10 transition-all cursor-pointer">
              <div className="w-12 h-12 rounded-xl bg-amber/15 border border-amber/30 flex items-center justify-center text-2xl mb-4">⚙</div>
              <p className="text-sm font-semibold text-text mb-1">Rule-Based NLP</p>
              <p className="text-xs text-dim leading-relaxed">
                Instant offline generation. Uses deterministic NLP rules — MC/DC, condition coverage, decision table. No AI required.
              </p>
              <div className="mt-4 flex items-center gap-2">
                <span className="text-[10px] px-2 py-0.5 rounded-full bg-green-500/30">Instant Without AI</span>
              </div>
            </button>

            {/* Claude AI card */}
            <button onClick={onClaudeGenerate}
              className="group text-left p-6 rounded-2xl border-2 border-amber/30 bg-amber/5 hover:border-amber hover:bg-amber/10 transition-all cursor-pointer">
              <div className="w-12 h-12 rounded-xl bg-amber/15 border border-amber/30 flex items-center justify-center text-2xl mb-4">✦</div>
              <p className="text-sm font-semibold text-text mb-1">Claude AI</p>
              <p className="text-xs text-dim leading-relaxed">
                Uses Claude Desktop via MCP. Generates richer, context-aware test cases with detailed preconditions and objectives.
              </p>
              <div className="mt-4 flex items-center gap-2">
                <span className="text-[10px] px-2 py-0.5 rounded-full bg-amber/30">AI-powered</span>
              </div>
            </button>
          </div>
        </div>
      )}
      {testCases.length > 0 && (
        <button
          onClick={onExport}
          className="fixed bottom-6 right-6 z-50 flex items-center gap-2 px-5 py-2.5 rounded-xl bg-amber text-bg text-sm font-semibold shadow-lg hover:bg-amber/90 transition-all"
        >
          Export Results →
        </button>
      )}
    </div>
  )
}

function PageExport({ testCases, summary, sessionId, exportSource }) {
  const dupCount = summary?.duplicates_removed ?? 0
  const hasResults = testCases.length > 0

  return (
    <div className="max-w-4xl mx-auto px-6 py-8">
      <div className="mb-8">
        <h2 className="text-xl font-semibold text-text">Export Results</h2>
        <p className="text-sm text-dim mt-1">Download your generated test cases as Excel or Word.</p>
      </div>

      {!hasResults ? (
        <div className="text-center py-16 border border-dashed border-border rounded-2xl">
          <p className="text-3xl mb-3">📋</p>
          <p className="text-sm font-medium text-text">No test cases to export yet</p>
          <p className="text-xs text-dim mt-1">Go to Generate and run the test case generator first</p>
        </div>
      ) : (
        <>
          {/* Summary stats */}
          {summary && (
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6">
              {[
                { label: 'Total test cases', value: summary.total },
                { label: 'Requirements covered',
                  value: (summary.requirements_total ?? 0) > 0
                    ? `${summary.requirements_covered ?? 0} / ${summary.requirements_total}`
                    : new Set((testCases || []).map(tc => tc.traceability_req_id).filter(Boolean)).size },
                { label: 'Duplicates removed', value: dupCount, red: dupCount > 0 },
                { label: 'Scenario types', value: Object.keys(summary.by_scenario_type || {}).length },
              ].map(s => (
                <div key={s.label}
                  className={`rounded-xl p-4 border ${s.red ? 'bg-red-500/8 border-red-500/30' : 'bg-card border-border'}`}>
                  <p className={`text-2xl font-semibold ${s.red ? 'text-red-400' : 'text-text'}`}>{s.value}</p>
                  <p className="text-xs text-dim mt-0.5">{s.label}</p>
                </div>
              ))}
            </div>
          )}

          {/* Download cards */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-6">
            <a
              href={exportSource === 'mcp' ? '/api/export/excel/mcp' : `/api/export/excel?session_id=${sessionId}`}
              download
              className="flex items-center gap-4 p-5 rounded-2xl border border-green-500/30 bg-green-500/5 hover:bg-green-500/10 transition-all group"
            >
              <div className="w-12 h-12 rounded-xl bg-green-500/15 border border-green-500/30 flex items-center justify-center text-2xl flex-shrink-0">📊</div>
              <div>
                <p className="text-sm font-semibold text-green-400">Download Excel</p>
                <p className="text-xs text-dim mt-0.5">.xlsx · Per-requirement sheets + summary</p>
              </div>
              <span className="ml-auto text-green-400/60 group-hover:text-green-400 transition-colors text-lg">↓</span>
            </a>

            <a
              href={exportSource === 'mcp' ? '/api/export/docx/mcp' : `/api/export/docx?session_id=${sessionId}`}
              download
              className="flex items-center gap-4 p-5 rounded-2xl border border-blue-500/30 bg-blue-500/5 hover:bg-blue-500/10 transition-all group"
            >
              <div className="w-12 h-12 rounded-xl bg-blue-500/15 border border-blue-500/30 flex items-center justify-center text-2xl flex-shrink-0">📄</div>
              <div>
                <p className="text-sm font-semibold text-blue-400">Download Word</p>
                <p className="text-xs text-dim mt-0.5">.docx · Formatted test case document</p>
              </div>
              <span className="ml-auto text-blue-400/60 group-hover:text-blue-400 transition-colors text-lg">↓</span>
            </a>
          </div>

          {/* Source note */}
          <p className="text-xs text-dim">
            {exportSource === 'mcp' ? '✦ Exporting Claude AI results' : '⚙ Exporting rule-based results'} · {testCases.length} test cases
          </p>
        </>
      )}
    </div>
  )
}

// ─── main App ─────────────────────────────────────────────────────────────────

const TABS = ['upload', 'configure', 'generate', 'export']
const TAB_LABELS = { upload: 'Upload', configure: 'Configure', generate: 'Generate', export: 'Export' }

export default function App() {
  const [tab, setTab] = useState('upload')

  // Upload
  const [files,    setFiles]    = useState({ srs: null, icd: null, supporting: null, supportingList: [] })
  const [loading,  setLoading]  = useState({ srs: false, icd: false, supporting: false })
  const [errors,   setErrors]   = useState({ srs: '', icd: '', supporting: '' })
  const [sessions, setSessions] = useState({ srs: null, icd: null, supporting: null })
  const [uploadData, setUploadData] = useState(null)

  const sessionsRef = useRef(sessions)
  sessionsRef.current = sessions

  // Config
  const [reqPrefixes,     setReqPrefixes]     = useState('')
  const [scopeConfig,     setScopeConfig]     = useState({ selectedReqIds: null, selectedModule: null, selectedModules: null })
  const [reviewPoints,    setReviewPoints]    = useState(DEFAULT_RP)
  const [customReviewPoints, setCustomReviewPoints] = useState([])

  // Generation
  const [generating, setGenerating] = useState(false)
  const [testCases,  setTestCases]  = useState([])
  const [summary,    setSummary]    = useState(null)
  const [error,      setError]      = useState('')
  const [progress,   setProgress]   = useState('')

  // MCP
  const [mode,         setMode]         = useState({ mode: 'offline' })
  const [mcpAvailable, setMcpAvailable] = useState(false)
  const [mcpResults,   setMcpResults]   = useState(null)
  const [aiWaiting,    setAiWaiting]    = useState(false)
  const [exportSource, setExportSource] = useState('session')

  useEffect(() => {
    fetch('/api/mode').then(r => r.ok ? r.json() : null).then(d => { if (d) setMode(d) }).catch(() => {})
  }, [])

  useEffect(() => {
    const id = setInterval(() => {
      fetch('/api/mcp/latest').then(r => r.ok ? r.json() : null).then(data => {
        if (data?.available && data.test_cases?.length > 0) {
          setMcpAvailable(true); setMcpResults(data); setAiWaiting(false)
        }
      }).catch(() => {})
    }, 3000)
    return () => clearInterval(id)
  }, [])

  // ── upload ──────────────────────────────────────────────────────────────────
  const handleFile = useCallback(async (type, f) => {
    if (!f) return
    const ext = '.' + f.name.split('.').pop().toLowerCase()
    if (!ACCEPTED.includes(ext)) {
      setErrors(e => ({ ...e, [type]: `Unsupported: ${ext}` })); return
    }
    setErrors(e => ({ ...e, [type]: '' }))
    setLoading(ld => ({ ...ld, [type]: true }))
    const form = new FormData(); form.append('file', f); form.append('doc_type', type)
    try {
      const res  = await fetch('/api/upload', { method: 'POST', body: form })
      const data = await res.json()
      if (!res.ok) throw new Error(data?.detail?.error || 'Upload failed')
      if (type === 'supporting') {
        // Multi-file: append to list
        setFiles(fs => ({
          ...fs,
          supportingList: [...(fs.supportingList || []), { name: f.name, session_id: data.session_id }]
        }))
        const next = { ...sessionsRef.current, supporting: data }
        setSessions(next)
        if (next.srs) {
          setUploadData(prev => ({
            ...next.srs,
            icd_session_id:         next.icd?.session_id || null,
            supporting_session_id:  data.session_id || null,
            supporting_session_ids: [...((prev||{}).supporting_session_ids||[]), data.session_id].filter(Boolean),
          }))
        }
      } else {
        setFiles(fs => ({ ...fs, [type]: f }))
        const next = { ...sessionsRef.current, [type]: data }
        setSessions(next)
        if (next.srs) {
          setUploadData(prev => ({
            ...next.srs,
            icd_session_id:         next.icd?.session_id        || null,
            supporting_session_id:  next.supporting?.session_id || null,
            supporting_session_ids: (prev||{}).supporting_session_ids || [],
          }))
          if (type === 'srs') { setTestCases([]); setSummary(null); setError('') }
        }
      }
    } catch (e) {
      setErrors(err => ({ ...err, [type]: e.message }))
      if (type !== 'supporting') setFiles(fs => ({ ...fs, [type]: null }))
    } finally {
      setLoading(ld => ({ ...ld, [type]: false }))
    }
  }, [])

  const handleClear = (type, idx) => {
    if (type === 'supporting' && idx !== undefined) {
      setFiles(fs => ({ ...fs, supportingList: fs.supportingList.filter((_, i) => i !== idx) }))
      return
    }
    setFiles(fs => ({ ...fs, [type]: null, ...(type === 'supporting' ? { supportingList: [] } : {}) }))
    setSessions(s => ({ ...s, [type]: null }))
    setErrors(e => ({ ...e, [type]: '' }))
    if (type === 'srs') { setUploadData(null); setTestCases([]); setSummary(null) }
  }

  // ── generate ────────────────────────────────────────────────────────────────
  const handleGenerate = async () => {
    if (!uploadData?.session_id) return
    setGenerating(true); setError(''); setTestCases([]); setSummary(null)
    setProgress('Analysing document…')
    try {
      setProgress('Ingesting requirements…')
      const res = await fetch('/api/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id:            uploadData.session_id,
          review_points:         reviewPoints,
          custom_review_points:  customReviewPoints.map(p => p.label),
          icd_session_id:        uploadData.icd_session_id        || null,
          supporting_session_id: uploadData.supporting_session_id || null,
          selected_req_ids:      scopeConfig.selectedReqIds || null,
          selected_module:       scopeConfig.selectedModule  || null,
          selected_modules:      scopeConfig.selectedModules || null,
          req_prefixes:          reqPrefixes.trim() ? reqPrefixes.split(',').map(p => p.trim()).filter(Boolean) : null,
        }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data?.detail?.error || data?.detail || 'Generation failed')
      setTestCases(data.test_cases); setSummary(data.summary)
      setExportSource('session'); setTab('generate')
    } catch (e) {
      setError(e.message); setTab('generate')
    } finally {
      setGenerating(false); setProgress('')
    }
  }

  const handleClaudeGenerate = async () => {
    if (!uploadData?.session_id) return
    setError(''); setTestCases([]); setSummary(null)
    try {
      const qRes = await fetch('/api/generate/ai', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id:            uploadData.session_id,
          icd_session_id:        uploadData.icd_session_id        || null,
          supporting_session_id: uploadData.supporting_session_id || null,
          selected_req_ids:      scopeConfig.selectedReqIds || null,
          selected_module:       scopeConfig.selectedModule  || null,
          req_prefixes:          reqPrefixes.trim() ? reqPrefixes.split(',').map(p => p.trim()).filter(Boolean) : null,
        }),
      })
      const qData = await qRes.json()
      if (!qRes.ok) { setError(qData?.detail?.suggestion || 'Failed to queue'); return }
      const total = qData.total_chunks ?? 0
      if (!total) { setError('No requirements found.'); return }
      const customPointLines = customReviewPoints.length > 0
        ? [
            '',
            'ADDITIONAL REVIEW POINTS (apply these during test case generation):',
            ...customReviewPoints.map((p, i) => `  ${i + 1}. ${p.label}`),
          ]
        : []
      // Strategy: for large docs use small batches + save after each
      // For small docs (<= 30 reqs) do it in one shot
      const BATCH_SIZE = total > 50 ? 10 : total > 30 ? 15 : total
      const totalBatches = Math.ceil(total / BATCH_SIZE)
      const batchSteps = totalBatches > 1
        ? [
            `This document has ${total} requirements across ${totalBatches} batches of ${BATCH_SIZE}.`,
            '',
            'CRITICAL RULE: Generate AND save each batch before moving to the next.',
            'Do NOT accumulate test cases across batches. Do NOT wait until the end to save.',
            '',
            `STEP 1: Call get_generated_test_cases(batch_index=0, batch_size=${BATCH_SIZE})`,
            'STEP 2: Generate test cases for ONLY those requirements.',
            'STEP 3: Immediately call save_enhanced_test_cases(test_cases=[...this batch only...], is_partial=True)',
            'STEP 4: Repeat steps 1-3 for batch_index 1, 2, 3, ... until is_last_batch=true.',
            'STEP 5: For the final batch call save_enhanced_test_cases with is_partial=False.',
            '',
            '⚠ WARNING: If you accumulate all batches before saving, the payload will exceed the 1MB limit and fail.',
          ]
        : [
            `STEP 1: Call tc-tool get_generated_test_cases with batch_size=${BATCH_SIZE}`,
            'STEP 2: Generate test cases for every requirement (normal, boundary, edge, robustness).',
            'STEP 3: Call tc-tool save_enhanced_test_cases with ALL test cases.',
          ]
      const prompt = [
        'Generate test cases for my SRS document using tc-tool.',
        '', ...batchSteps, '',
        'For each requirement generate: normal, boundary, edge, and robustness scenarios.',
        'Every test case MUST have: traceability_req_id, test_case_id, scenario_id,',
        'inputs (["SignalName = Value"]), expected_outcome ("OutputSignal = Value."),',
        'design_methodology, testing_type, scenario_type, priority, objective,',
        'preconditions, test_steps, dependent_test_cases, test_environment, remarks, module',
        ...customPointLines,
        '', `Total requirements: ${total}`,
      ].join('\n')
      await navigator.clipboard.writeText(prompt).catch(() => {})
      setAiWaiting(true)
      setTab('generate')
      // Directly launch Claude Desktop and run the full paste+send automation.
      // (Previously this was gated behind a manual popup + button click.)
      await fetch('/api/open-claude', { method: 'POST' }).catch(() => {})
    } catch (e) { setError(e.message) }
  }

  const handleLoadMcp = () => {
    if (!mcpResults) return
    setTestCases(mcpResults.test_cases); setSummary(mcpResults.summary)
    setMcpAvailable(false); setExportSource('mcp')
  }

  const handleRemindClaude = async () => {
    await navigator.clipboard.writeText('Please call tc-tool save_enhanced_test_cases now.').catch(() => {})
  }

  // tab accessibility
  const tabAllowed = (t) => {
    if (t === 'upload') return true
    if (t === 'configure' || t === 'generate' || t === 'export') return !!uploadData
    return false
  }

  const isMcp = mode?.mode === 'online'

  return (
    <div className="h-screen flex flex-col bg-bg text-text font-sans overflow-hidden">

      {/* ── Top bar ── */}
      <header className="flex-shrink-0 border-b border-border bg-surface z-10">
        <div className="relative flex items-center h-12 px-5">
          <div className="flex items-center gap-2.5">
            <div className="w-7 h-7 rounded-lg bg-amber/10 border border-amber/30 flex items-center justify-center text-amber text-xs">⚙</div>
            <div>
              <p className="text-xs font-semibold text-text leading-none"> Test Case Generator</p>
              <p class="text-[10px] text-dim font-mono">AI Based Test Case Generation</p>
            </div>
          </div>

          {/* Tab navigation */}
          <nav className="absolute left-1/2 -translate-x-1/2 flex items-center">
            {TABS.map((t, i) => {
              const allowed  = tabAllowed(t)
              const isActive = tab === t
              const isDone   = (t === 'upload' && !!uploadData) ||
                               (t === 'configure' && !!uploadData) ||
                               (t === 'generate' && testCases.length > 0) ||
                               (t === 'export'   && testCases.length > 0)
              return (
                <div key={t} className="flex items-center">
                  <button
                    onClick={() => allowed && setTab(t)}
                    disabled={!allowed}
                    className={`flex items-center gap-1.5 px-4 py-3 text-xs border-b-2 transition-all
                      ${isActive
                        ? 'border-amber text-text font-medium'
                        : allowed
                          ? isDone
                            ? 'border-transparent text-green-400 hover:border-green-500/40 cursor-pointer'
                            : 'border-transparent text-dim hover:text-text hover:border-border cursor-pointer'
                          : 'border-transparent text-dim/40 cursor-not-allowed'}`}
                  >
                    <span className={`w-4 h-4 rounded-full flex items-center justify-center text-[9px] font-bold flex-shrink-0
                      ${isActive  ? 'bg-amber/20 text-amber'
                      : isDone    ? 'bg-green-500/20 text-green-400'
                      : allowed   ? 'bg-surface text-dim'
                      :             'bg-surface/50 text-dim/40'}`}>
                      {isDone && !isActive ? '✓' : i + 1}
                    </span>
                    {TAB_LABELS[t]}
                  </button>
                  {i < TABS.length - 1 && (
                    <span className="text-border/60 text-xs px-0.5">›</span>
                  )}
                </div>
              )
            })}
          </nav>
        </div>
      </header>

      {/* ── Tab content ── */}
      <div className="flex-1 overflow-auto">

        {tab === 'upload' && (
          <PageUpload
            files={files} loading={loading} errors={errors}
            onFile={handleFile} onClear={handleClear}
            onNext={() => setTab('configure')}
            reqPrefixes={reqPrefixes}
            onReqPrefixesChange={setReqPrefixes}
          />
        )}

        {tab === 'configure' && (
          <PageConfigure
            sessionId={uploadData?.session_id}
            scopeConfig={scopeConfig}    onScopeChange={setScopeConfig}
            reqPrefixes={reqPrefixes}
            reviewPoints={reviewPoints}  onRpChange={(id, v) => setReviewPoints(rp => ({ ...rp, [id]: v }))}
            customReviewPoints={customReviewPoints} onCustomReviewPointsChange={setCustomReviewPoints}
            generating={generating}
            onBack={() => setTab('upload')}
            onGenerate={handleGenerate}
            onNext={() => setTab('generate')}
          />
        )}

        {tab === 'generate' && (
          <div className="flex flex-col" style={{ height: 'calc(100vh - 48px)' }}>
            <PageGenerate
              testCases={testCases} summary={summary}
              generating={generating} progress={progress} error={error} aiWaiting={aiWaiting}
              uploadDone={!!uploadData}
              onGenerate={handleGenerate}
              onClaudeGenerate={handleClaudeGenerate}
              onRemindClaude={handleRemindClaude}
              onLoadMcp={handleLoadMcp}
              mcpAvailable={mcpAvailable} mcpResults={mcpResults}
              onExport={() => setTab('export')}
            />
          </div>
        )}

        {tab === 'export' && (
          <PageExport
            testCases={testCases} summary={summary}
            sessionId={uploadData?.session_id}
            exportSource={exportSource}
          />
        )}
      </div>
    </div>
  )
}