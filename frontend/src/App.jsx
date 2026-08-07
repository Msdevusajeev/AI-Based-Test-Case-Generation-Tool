import { useState, useEffect, useRef, useCallback } from 'react'
import ReviewPointsPanel, { ALL_REVIEW_POINTS } from './components/ReviewPointsPanel'
import ResultsTable      from './components/TCTable'
import ScopeSelector     from './components/ScopeSelector'

const DEFAULT_RP = { rp1: true, rp2: true, rp3: true, rp4: true, rp5: true, rp6: false }

// Claude Desktop Skills don't use slash-command syntax (that's a Claude Code/CLI
// feature) — Claude decides to use a skill by matching its name/description
// against the request. So we name it explicitly in plain language instead.
// Also requires: the "general-tc-skill" skill uploaded & toggled ON in
// Customize > Skills, with Code execution and file creation enabled.
const TC_SKILL_INSTRUCTION = "Use the general-tc-skill skill for test case generation. This skill defines the project's test case generation workflow, requirement classification guidelines, coverage strategy, and quality validation criteria to ensure consistent and comprehensive test case creation."
const ACCEPTED   = ['.pdf', '.docx', '.xlsx', '.txt']
const MAX_DOCS_PER_SECTION = 5   // cap for SRS / ICD multi-document upload
const MAX_SUPPORTING_DOCS  = 10  // cap for Supporting Document multi-document upload

// ─── tiny helpers ─────────────────────────────────────────────────────────────

function formatBytes(n) {
  if (!n) return ''
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / (1024 * 1024)).toFixed(2)} MB`
}

// ─── Duplicate-document modal ───────────────────────────────────────────────

function DuplicateDocModal({ fileName, sameSection, onClose }) {
  if (!fileName) return null
  const locationText = sameSection ? 'in this section' : 'in another section'
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={onClose}>
      <div
        className="bg-card border border-red-500/30 rounded-xl p-6 max-w-md w-full mx-4 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-2 mb-3">
          <span className="text-red-400 text-xl">⚠</span>
          <h3 className="text-text text-sm font-semibold">Duplicate Document</h3>
        </div>
        <p className="text-dim text-sm leading-relaxed">
          Duplicate document detected. The file '{fileName}' has already been uploaded {locationText}. Please upload a unique document.
        </p>
        <div className="flex justify-end mt-5">
          <button
            className="px-4 py-2 rounded-lg bg-amber/10 border border-amber/30 text-amber text-xs font-mono font-bold hover:bg-amber/20"
            onClick={onClose}
          >
            OK
          </button>
        </div>
      </div>
    </div>
  )
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
      <input ref={ref} type="file" accept=".pdf,.docx,.xlsx,.txt" className="hidden"
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
              {ext === 'pdf' ? '📄' : ext === 'docx' || ext === 'doc' ? '📝' : ext === 'txt' ? '📃' : '📊'}
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

// ─── Multi-document drop zone (used by SRS / ICD / Supporting) ───────────────
// Same look & behaviour the Supporting-docs section already had: a list of
// uploaded files plus an "add another" drop target, capped at maxFiles.

function MultiDropZone({ list, maxFiles, label, required, error, loading, onFiles, onClear }) {
  const inputId = `multi-input-${label.replace(/\s+/g, '-')}`
  const items = list || []
  const atLimit = items.length >= maxFiles

  return (
    <div className="space-y-2">
      {loading && (
        <div className="flex items-center gap-3 px-4 py-2.5 rounded-xl border border-border bg-card">
          <div className="w-4 h-4 border-2 border-amber border-t-transparent rounded-full spin" />
          <p className="text-dim text-xs">Uploading…</p>
        </div>
      )}
      {items.map((f, idx) => (
        <div key={idx} className="flex items-center gap-3 px-4 py-2.5 rounded-xl border border-green-500/30 bg-green-500/5">
          <span className="text-xl">{f.name?.endsWith('.pdf') ? '📄' : f.name?.endsWith('.docx') ? '📝' : f.name?.endsWith('.txt') ? '📃' : '📊'}</span>
          <div className="flex-1 min-w-0">
            <p className="text-sm text-text truncate">{f.name}</p>
            <p className="text-xs text-green-400">✓ Uploaded</p>
          </div>
          <button onClick={() => onClear(idx)}
            className="text-dim hover:text-red-400 transition-colors text-xs px-2 py-1 rounded hover:bg-red-500/10">
            ✕
          </button>
        </div>
      ))}

      {!atLimit && (
        <div
          className="rounded-xl border-2 border-dashed border-border hover:border-amber/40 bg-card transition-all cursor-pointer"
          onClick={() => document.getElementById(inputId).click()}
          onDragOver={e => e.preventDefault()}
          onDrop={e => { e.preventDefault(); onFiles(Array.from(e.dataTransfer.files)) }}
        >
          <input id={inputId} type="file" accept=".pdf,.docx,.xlsx,.txt" multiple className="hidden"
            onClick={e => { e.target.value = '' }}
            onChange={e => { onFiles(Array.from(e.target.files)); e.target.value = '' }} />
          <div className="p-4 flex items-center gap-4">
            <div className="w-10 h-10 rounded-xl border border-border bg-surface flex items-center justify-center text-xl flex-shrink-0">📋</div>
            <div>
              <p className="text-sm text-text font-medium">
                {items.length > 0 ? 'Add another document' : `Drop ${label} here or`}&nbsp;
                <span className="text-amber underline">Click to browse</span>
              </p>
              <div className="flex items-center gap-2 mt-1">
                {ACCEPTED.map(e => (
                  <span key={e} className="px-1.5 py-0.5 rounded text-[10px] font-mono bg-border text-dim">{e}</span>
                ))}
                <span className="text-[10px] text-dim/60 ml-1">
                  {Number.isFinite(maxFiles) ? `Up to ${maxFiles} files` : 'Multiple files supported'}
                  {required ? ' · at least 1 required' : ''}
                </span>
              </div>
            </div>
          </div>
        </div>
      )}

      {atLimit && (
        <p className="text-[10px] text-dim/60 px-1">Maximum of {maxFiles} documents reached. Remove one to add another.</p>
      )}

      {error && <p className="px-1 text-xs text-red-400">⚠ {error}</p>}
    </div>
  )
}

// ─── Page: Upload ─────────────────────────────────────────────────────────────

function PageUpload({ files, loading, errors, onFiles, onClear, onNext, reqPrefixes, onReqPrefixesChange }) {
  const srsReady    = (files.srsList || []).length > 0
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
          <MultiDropZone
            label="SRS document" required maxFiles={MAX_DOCS_PER_SECTION}
            list={files.srsList} error={errors.srs} loading={loading.srs}
            onFiles={arr => onFiles('srs', arr)} onClear={idx => onClear('srs', idx)} />
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
          <MultiDropZone
            label="ICD document" maxFiles={MAX_DOCS_PER_SECTION}
            list={files.icdList} error={errors.icd} loading={loading.icd}
            onFiles={arr => onFiles('icd', arr)} onClear={idx => onClear('icd', idx)} />
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
          {/* Multi supporting documents — capped at MAX_SUPPORTING_DOCS */}
          <MultiDropZone
            label="supporting documents" maxFiles={MAX_SUPPORTING_DOCS}
            list={files.supportingList} error={errors.supporting}
            onFiles={arr => onFiles('supporting', arr)} onClear={idx => onClear('supporting', idx)} />
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

function PageConfigure({ sessionId, scopeConfig, onScopeChange, reviewPoints, onRpChange, customReviewPoints, onCustomReviewPointsChange, generating, onBack, onGenerate, onNext, reqPrefixes, domain, onDomainChange }) {
  const DOMAIN_OPTIONS = [
    { value: 'avionics',   label: 'Avionics (DO-178C)' },
    { value: 'automotive', label: 'Automotive (ISO 26262)' },
    { value: 'healthcare', label: 'Healthcare (IEC 62304)' },
    { value: 'general',    label: 'General (ISO/IEC/IEEE 29119)' },
  ]
  return (
    <div className="max-w-5xl mx-auto px-6 py-8">
      <div className="mb-8">
        <h2 className="text-xl font-semibold text-text">Configure Generation</h2>
        <p className="text-sm text-dim mt-1">Select which requirements to target and choose your review points.</p>
      </div>

      {/* Domain — defaults Safety_Level / Test_Level / Standard_Reference */}
      <div className="bg-card border border-border rounded-2xl p-5 mb-6">
        <div className="flex items-center gap-2 mb-3">
          <div className="w-6 h-6 rounded-lg bg-amber/10 border border-amber/30 flex items-center justify-center text-amber text-xs">🏷</div>
          <h3 className="text-sm font-semibold text-text">Domain</h3>
          <span className="text-xs text-dim ml-1">— sets default Safety_Level / Test_Level / Standard_Reference (editable per test case after generation)</span>
        </div>
        <select
          value={domain}
          onChange={e => onDomainChange(e.target.value)}
          disabled={generating}
          className="bg-surface border border-border text-dim text-sm rounded-lg px-3 py-2 focus:outline-none focus:border-amber/50 cursor-pointer"
        >
          {DOMAIN_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
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

const STAGES = ['Request Submitted', 'Requirement Analysis', 'Test Case Generation', 'Completion']

function StageStepper({ stage, activityLog, requestId, controlState }) {
  if (!stage) return null
  const idx = STAGES.indexOf(stage)
  const last = activityLog[activityLog.length - 1]
  return (
    <div className="flex-shrink-0 mx-6 mt-3 px-4 py-2.5 rounded-xl bg-card border border-border">
      <div className="flex items-center gap-2">
        {STAGES.map((s, i) => (
          <div key={s} className="flex items-center gap-2 flex-1">
            <span className={`text-[10px] px-2 py-1 rounded-full whitespace-nowrap border ${
              i < idx || (stage === 'Completion' && i <= idx) ? 'border-green-500/30 text-green-400 bg-green-500/10'
              : i === idx ? 'border-amber/40 text-amber bg-amber/10'
              : 'border-border text-dim'
            }`}>{s}</span>
            {i < STAGES.length - 1 && <div className="flex-1 h-px bg-border" />}
          </div>
        ))}
        {controlState === 'paused' && (
          <span className="text-[10px] px-2 py-1 rounded-full whitespace-nowrap border border-amber/40 text-amber bg-amber/10 flex-shrink-0">⏸ Paused</span>
        )}
        {controlState === 'stopped' && (
          <span className="text-[10px] px-2 py-1 rounded-full whitespace-nowrap border border-red-500/40 text-red-400 bg-red-500/10 flex-shrink-0">⏹ Stopped</span>
        )}
      </div>
      <div className="flex items-center justify-between mt-1.5">
        {last?.detail ? <p className="text-[10px] text-dim">{last.detail}</p> : <span />}
      </div>
    </div>
  )
}

function GenerationControls({ stage, controlState, onPause, onResume, onStop }) {
  // Only meaningful once a run is actually in flight and hasn't been stopped.
  if (!stage || stage === 'Completion' || controlState === 'stopped') return null
  return (
    <div className="flex-shrink-0 mx-6 mt-3">
      <div className="flex items-center gap-2">
        {controlState === 'paused' ? (
          <button onClick={onResume}
            title="Copies a reminder to your clipboard — paste it into the existing Claude Desktop chat to actually get it moving again."
            className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border border-green-500/40 text-green-400 hover:bg-green-500/10 transition-all">
            ▶ Resume
          </button>
        ) : (
          <button onClick={onPause}
            className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border border-amber/40 text-amber hover:bg-amber/10 transition-all">
            ⏸ Pause
          </button>
        )}
        <button onClick={() => { if (confirm("Stop generation? Test cases already saved before this point are kept and available in Load Results. Any batch Claude is mid-generating right now will be rejected when it tries to save — it will not be recovered.")) onStop() }}
          className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border border-red-500/40 text-red-400 hover:bg-red-500/10 transition-all">
          ⏹ Stop
        </button>
      </div>
      {controlState === 'paused' && (
        <p className="text-[10px] text-dim mt-1.5">
          A reminder was copied to your clipboard — paste it into the Claude Desktop chat that's running this generation so it actually retries, since pausing here can't reach into its already-running turn.
        </p>
      )}
    </div>
  )
}

function ErrorBanner({ wsError, onDismiss }) {
  if (!wsError) return null
  return (
    <div className="flex-shrink-0 mx-6 mt-3 px-4 py-2.5 rounded-xl bg-red-500/5 border border-red-500/30 flex items-start justify-between gap-3">
      <p className="text-xs text-red-400">{wsError.message}</p>
      <button onClick={onDismiss} className="text-[10px] text-dim hover:text-red-400 flex-shrink-0">Dismiss</button>
    </div>
  )
}

function ClarificationBanner({ clarification, onAnswer }) {
  const [answer, setAnswer]         = useState('')
  const [showFreeText, setShowFreeText] = useState(false)

  useEffect(() => { setAnswer(''); setShowFreeText(false) }, [clarification])

  if (!clarification) return null
  const { question, options } = clarification
  const submitFreeText = () => { if (answer.trim()) onAnswer(answer.trim()) }

  return (
    <div className="flex-shrink-0 mx-6 mt-3 px-4 py-3 rounded-xl bg-blue-500/5 border border-blue-500/30">
      <p className="text-xs text-blue-400 font-medium mb-2">Claude needs clarification</p>
      <p className="text-xs text-text mb-3">{question}</p>

      {Array.isArray(options) && options.length > 0 && !showFreeText && (
        <div className="flex flex-col gap-1.5 mb-2">
          {options.map((opt, i) => (
            <button
              key={i}
              onClick={() => onAnswer(opt)}
              className="flex items-center gap-2.5 text-left text-xs px-3 py-2 rounded-lg border border-border bg-bg hover:border-blue-500/40 hover:bg-blue-500/5 transition-all"
            >
              <span className="flex-shrink-0 w-4 h-4 flex items-center justify-center text-[10px] rounded bg-card border border-border text-dim">
                {i + 1}
              </span>
              {opt}
            </button>
          ))}
        </div>
      )}

      {(showFreeText || !options?.length) ? (
        <div className="flex gap-2">
          <input
            autoFocus
            value={answer}
            onChange={e => setAnswer(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && submitFreeText()}
            placeholder="Type your answer…"
            className="flex-1 text-xs px-3 py-1.5 rounded-lg bg-bg border border-border focus:border-blue-500/50 outline-none"
          />
          <button onClick={submitFreeText}
            className="text-xs px-3 py-1.5 rounded-lg bg-blue-500 text-white font-medium hover:bg-blue-600 transition-all">
            Send
          </button>
        </div>
      ) : (
        <div className="flex items-center gap-3">
          <button onClick={() => setShowFreeText(true)}
            className="text-[11px] text-dim hover:text-blue-400 transition-colors underline">
            Something else
          </button>
          <button onClick={() => onAnswer('(user chose to skip — proceed using your best judgement)')}
            className="text-[11px] text-dim hover:text-text transition-colors underline">
            Skip
          </button>
        </div>
      )}
    </div>
  )
}

function PageGenerate({
  testCases, summary, generating, progress, error, aiWaiting,
  uploadDone, onGenerate, onClaudeGenerate, onRemindClaude,
  onLoadMcp, mcpAvailable, mcpResults, onExport,
  stage, activityLog = [], requestId, clarification, onAnswerClarification,
  wsError, onDismissError,
  controlState = 'running', onPause, onResume, onStop,
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

      {/* Live processing status, pushed over the WebSocket layer */}
      <StageStepper stage={stage} activityLog={activityLog} requestId={requestId} controlState={controlState} />
      <GenerationControls stage={stage} controlState={controlState} onPause={onPause} onResume={onResume} onStop={onStop} />
      <ErrorBanner wsError={wsError} onDismiss={onDismissError} />
      <ClarificationBanner clarification={clarification} onAnswer={onAnswerClarification} />

      {/* AI waiting (shown until the first real status event arrives) */}
      {aiWaiting && !stage && (
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

// ─── Coverage gap report ────────────────────────────────────────────────────
// Surfaces GET /api/coverage/report — the deterministic (non-AI) check added
// alongside output_validator.check_coverage: MC/DC signal pairing, missing
// baselines, broken dependency links, empty expected_outcome. This is a
// floor, not a substitute for engineering review — it can only flag gaps in
// test cases that were generated, not requirement behaviour nobody wrote a
// test case for at all.
function CoveragePanel({ hasResults, refreshKey }) {
  const [report,   setReport]   = useState(null)
  const [loading,  setLoading]  = useState(false)
  const [expanded, setExpanded] = useState(false)

  useEffect(() => {
    if (!hasResults) { setReport(null); return }
    setLoading(true)
    fetch('/api/coverage/report')
      .then(r => r.ok ? r.json() : null)
      .then(d => setReport(d?.available ? d.report : null))
      .catch(() => setReport(null))
      .finally(() => setLoading(false))
  }, [hasResults, refreshKey])

  if (!hasResults) return null

  return (
    <div className="mb-6 rounded-2xl border border-border bg-card p-5">
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="text-sm font-semibold text-text">Coverage Gap Report</p>
          <p className="text-xs text-dim mt-0.5">
            Deterministic check — MC/DC pairing, baselines, dependency links, empty outcomes.
            Not a substitute for engineering review.
          </p>
        </div>
        {loading && <div className="w-4 h-4 border-2 border-amber border-t-transparent rounded-full spin flex-shrink-0" />}
      </div>

      {report && (
        <div className="mt-4">
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <div className="rounded-xl p-3 border border-border bg-bg">
              <p className="text-xl font-semibold text-text">{report.total_requirement_groups}</p>
              <p className="text-[11px] text-dim mt-0.5">Test case groups</p>
            </div>
            <div className={`rounded-xl p-3 border ${report.groups_with_gaps > 0 ? 'bg-red-500/8 border-red-500/30' : 'bg-green-500/8 border-green-500/30'}`}>
              <p className={`text-xl font-semibold ${report.groups_with_gaps > 0 ? 'text-red-400' : 'text-green-400'}`}>{report.groups_with_gaps}</p>
              <p className="text-[11px] text-dim mt-0.5">Groups with gaps</p>
            </div>
            <div className="rounded-xl p-3 border border-border bg-bg">
              <p className="text-xl font-semibold text-text">{report.groups_clean}</p>
              <p className="text-[11px] text-dim mt-0.5">Clean groups</p>
            </div>
            <div className="rounded-xl p-3 border border-border bg-bg">
              <p className="text-xl font-semibold text-text">{report.total_gaps}</p>
              <p className="text-[11px] text-dim mt-0.5">Total gaps</p>
            </div>
          </div>

          {report.total_gaps > 0 && (
            <>
              <div className="flex flex-wrap gap-2 mt-4">
                {Object.entries(report.gaps_by_category).map(([cat, count]) => (
                  <span key={cat}
                    className="text-[10px] px-2 py-1 rounded-full bg-red-500/10 border border-red-500/25 text-red-400 font-mono">
                    {cat.replace(/_/g, ' ')}: {count}
                  </span>
                ))}
              </div>

              <button onClick={() => setExpanded(e => !e)}
                className="mt-3 text-xs text-amber underline hover:no-underline">
                {expanded ? 'Hide details' : `Show ${report.total_gaps} gap details`}
              </button>

              {expanded && (
                <div className="mt-3 max-h-64 overflow-auto rounded-lg border border-border divide-y divide-border">
                  {report.gap_details.map((g, i) => (
                    <div key={i} className="p-3 text-xs">
                      <p className="font-mono text-dim">{g.traceability_req_id} · {g.test_case_id} · {g.category.replace(/_/g, ' ')}</p>
                      <p className="text-text mt-1">{g.detail}</p>
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
        </div>
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
          <CoveragePanel hasResults={hasResults} refreshKey={testCases.length} />

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

          {/* Verification depth — code-computed scenario-type diversity per
              requirement, independent of whatever Claude's own RTM/testability
              summary claims. Falls back to a client-side computation from
              testCases if this summary predates the backend field. */}
          {summary && (() => {
            const CORE = ['normal', 'boundary', 'edge', 'robustness']
            const ADV_LABELS = { mcdc: 'MC/DC', beyond_range: 'Beyond-Range', fault: 'Fault Injection', timing: 'Timing', invalid_input: 'ICD Invalid-Range' }
            let depth = summary.verification_depth
            if (!depth) {
              const byReq = {}
              for (const tc of (testCases || [])) {
                const rid = tc.traceability_req_id
                const st  = (tc.scenario_type || '').toLowerCase().trim()
                if (rid && st) (byReq[rid] ||= new Set()).add(st)
              }
              const gaps = {}
              const advUsage = {}
              for (const [rid, types] of Object.entries(byReq)) {
                const missing = CORE.filter(c => !types.has(c))
                if (missing.length) gaps[rid] = missing
                for (const k of Object.keys(ADV_LABELS)) if (types.has(k)) advUsage[k] = (advUsage[k] || 0) + 1
              }
              depth = { core_scenario_gaps: gaps, advanced_scenario_usage: advUsage }
            }
            const gapEntries = Object.entries(depth.core_scenario_gaps || {})
            const advanced   = depth.advanced_scenario_usage || {}
            const advTotal   = Object.values(advanced).reduce((a, b) => a + b, 0)
            return (
              <div className="rounded-xl p-4 border border-border bg-card mb-6 space-y-3">
                <div className="flex items-center justify-between">
                  <p className="text-xs text-dim uppercase tracking-widest font-mono">Verification Depth</p>
                  <span className="text-[10px] text-dim">code-computed, not self-reported</span>
                </div>
                <div className="flex flex-wrap gap-2">
                  {gapEntries.length === 0 ? (
                    <span className="text-xs px-2 py-1 rounded-full border border-green-500/30 text-green-400 bg-green-500/10">
                      ✓ Every requirement has all 4 core scenario types
                    </span>
                  ) : (
                    <span className="text-xs px-2 py-1 rounded-full border border-amber/40 text-amber bg-amber/10">
                      ⚠ {gapEntries.length} requirement{gapEntries.length !== 1 ? 's' : ''} missing a core scenario type
                    </span>
                  )}
                  {Object.keys(ADV_LABELS).map(k => advanced[k] ? (
                    <span key={k} className={`text-xs font-mono px-2 py-1 rounded-full badge-${k}`}>
                      {ADV_LABELS[k]} × {advanced[k]}
                    </span>
                  ) : null)}
                  {advTotal === 0 && (
                    <span className="text-xs px-2 py-1 rounded-full border border-border text-dim">
                      No MC/DC, Beyond-Range, Fault, or Timing test cases in this run
                    </span>
                  )}
                </div>
                {gapEntries.length > 0 && (
                  <details className="text-xs text-dim">
                    <summary className="cursor-pointer hover:text-text">Show requirements with gaps ({gapEntries.length})</summary>
                    <div className="mt-2 space-y-1 max-h-40 overflow-y-auto">
                      {gapEntries.map(([rid, missing]) => (
                        <div key={rid} className="flex items-center gap-2 font-mono">
                          <span className="text-text">{rid}</span>
                          <span className="text-dim">missing:</span>
                          <span className="text-amber">{missing.join(', ')}</span>
                        </div>
                      ))}
                    </div>
                  </details>
                )}
              </div>
            )
          })()}

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
  // srsList / icdList: up to MAX_DOCS_PER_SECTION docs each, [{name, session_id}]
  const [files,    setFiles]    = useState({ srsList: [], icdList: [], supportingList: [] })
  const [loading,  setLoading]  = useState({ srs: false, icd: false, supporting: false })
  const [errors,   setErrors]   = useState({ srs: '', icd: '', supporting: '' })
  // sessions.srs / sessions.icd hold the single (possibly merged) session that
  // downstream /api/generate, /api/generate/ai, /api/scope calls consume —
  // unchanged contract, just now potentially backed by several source files.
  const [sessions, setSessions] = useState({ srs: null, icd: null, supporting: null })
  const [uploadData, setUploadData] = useState(null)
  const [duplicateFile, setDuplicateFile] = useState(null)
  const [duplicateSameSection, setDuplicateSameSection] = useState(false)

  const sessionsRef = useRef(sessions)
  sessionsRef.current = sessions
  const filesRef = useRef(files)
  filesRef.current = files

  // Config
  const [reqPrefixes,     setReqPrefixes]     = useState('')
  const [scopeConfig,     setScopeConfig]     = useState({ selectedReqIds: null, selectedModule: null, selectedModules: null })
  const [reviewPoints,    setReviewPoints]    = useState(DEFAULT_RP)
  const [customReviewPoints, setCustomReviewPoints] = useState([])
  // Domain selector — defaults Safety_Level / Test_Level / Standard_Reference
  // in the standardized Test Case Template (see constants.DOMAIN_DEFAULTS on
  // the backend). This is a starting point for review, not a per-requirement
  // DAL/ASIL classification — editable per-TC after generation.
  const [domain, setDomain] = useState('general')

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

  // Live status from the WebSocket layer: current stage, rolling activity log,
  // any clarification question Claude Desktop is waiting on, the last error,
  // and the request_id of the run currently being tracked.
  const [stage,          setStage]          = useState(null)   // e.g. "Test Case Generation"
  const [activityLog,    setActivityLog]    = useState([])     // [{ts, stage/answer, detail}]
  const [clarification,  setClarification]  = useState(null)   // {question, options} | null
  const [wsError,        setWsError]        = useState(null)   // {message} | null
  const [requestId,      setRequestId]      = useState(null)
  const [controlState,   setControlState]   = useState('running')  // running / paused / stopped

  useEffect(() => {
    fetch('/api/mode').then(r => r.ok ? r.json() : null).then(d => { if (d) setMode(d) }).catch(() => {})
  }, [])

  // Reconcile with the real backend Job Status on load — the websocket
  // 'control' event only fires on the *next* change, so a page reload/
  // reconnect would otherwise silently default to 'running' even if the
  // backend is actually PAUSED or STOPPED from before the reload.
  useEffect(() => {
    fetch('/api/job/status').then(r => r.ok ? r.json() : null).then(d => {
      if (d?.job_status) setControlState(d.job_status.toLowerCase())
    }).catch(() => {})
  }, [])

  const handleMcpResult = useCallback((data) => {
    if (data && data.test_cases?.length > 0) {
      setMcpAvailable(true); setMcpResults(data); setAiWaiting(false)
    }
  }, [])

  // Real-time status/clarification/result channel. Falls back to the slower
  // /api/mcp/latest poll below if the socket is ever down.
  useEffect(() => {
    let ws, reconnectTimer, alive = true

    const connect = () => {
      const proto = location.protocol === 'https:' ? 'wss' : 'ws'
      ws = new WebSocket(`${proto}://${location.host}/ws/status`)

      ws.onmessage = (evt) => {
        let msg
        try { msg = JSON.parse(evt.data) } catch { return }
        if (msg.request_id) setRequestId(msg.request_id)

        if (msg.type === 'status') {
          setStage(msg.stage)
          setActivityLog(log => [...log.slice(-49), msg])
          if (msg.stage && msg.stage !== 'Completion') setAiWaiting(true)
        } else if (msg.type === 'control') {
          setControlState(msg.state)
          setActivityLog(log => [...log.slice(-49), msg])
          if (msg.state === 'stopped') setAiWaiting(false)
        } else if (msg.type === 'clarification_question') {
          setClarification({ question: msg.question, options: msg.options || null })
          setActivityLog(log => [...log.slice(-49), msg])
        } else if (msg.type === 'user_response') {
          setClarification(null)
          setActivityLog(log => [...log.slice(-49), msg])
        } else if (msg.type === 'result') {
          handleMcpResult({ available: true, test_cases: msg.test_cases, summary: msg.summary })
        } else if (msg.type === 'error') {
          setWsError({ message: msg.message })
          setActivityLog(log => [...log.slice(-49), msg])
        }
      }

      ws.onclose = () => { if (alive) reconnectTimer = setTimeout(connect, 2000) }
      ws.onerror = () => ws.close()
    }

    connect()
    return () => { alive = false; clearTimeout(reconnectTimer); ws?.close() }
  }, [handleMcpResult])

  useEffect(() => {
    const id = setInterval(() => {
      fetch('/api/mcp/latest').then(r => r.ok ? r.json() : null).then(handleMcpResult).catch(() => {})
    }, 10000)  // low-frequency fallback only — WS carries the real-time updates
    return () => clearInterval(id)
  }, [handleMcpResult])

  const answerClarification = useCallback(async (answer) => {
    try {
      await fetch('/api/clarify/respond', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ answer }),
      })
      setClarification(null)
    } catch {}
  }, [])

  // ── generation control: pause / resume / stop ────────────────────────────
  // Optimistic local update for instant feedback; the 'control' WS event
  // (broadcast by the backend once it's actually flipped the flag) reconciles
  // this if anything raced. Actual enforcement happens server-side — these
  // buttons make the backend refuse further batches/saves, they don't reach
  // into Claude's live turn.
  const pauseGeneration = useCallback(async () => {
    setControlState('paused')
    try { await fetch('/api/job/pause', { method: 'POST' }) } catch {}
  }, [])

  const resumeGeneration = useCallback(async () => {
    setControlState('running')
    try { await fetch('/api/job/resume', { method: 'POST' }) } catch {}
    // Flipping the backend flag doesn't reach into Claude Desktop's already-running
    // chat turn — Claude only sees "resumed" the next time it calls a tool, and it
    // has no reason to call one on its own after being told to hold. Put the nudge
    // on the clipboard so the user can paste it into the existing chat.
    await navigator.clipboard.writeText(
      'Generation has been resumed. Retry the save_enhanced_test_cases call that was just held, then continue with the remaining batches as before.'
    ).catch(() => {})
  }, [])

  const stopGeneration = useCallback(async () => {
    setControlState('stopped')
    try {
      const res  = await fetch('/api/job/stop', { method: 'POST' })
      const data = await res.json()
      if (data?.salvaged_test_cases > 0) {
        // Pull whatever was salvaged into view immediately.
        fetch('/api/mcp/latest').then(r => r.ok ? r.json() : null).then(handleMcpResult).catch(() => {})
      }
    } catch {}
  }, [handleMcpResult])

  // ── upload ──────────────────────────────────────────────────────────────────

  // Combine 1..N /api/upload session_ids of the same doc_type into the single
  // session_id the rest of the app already knows how to consume. With exactly
  // one id, this is a no-op pass-through (existing single-document behaviour
  // is untouched) — /api/merge_sessions itself special-cases that too.
  const mergeSessions = useCallback(async (sessionIds, docType) => {
    if (sessionIds.length === 1) return { session_id: sessionIds[0] }
    const res = await fetch('/api/merge_sessions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_ids: sessionIds, doc_type: docType }),
    })
    const data = await res.json()
    if (!res.ok) throw new Error(data?.detail?.error || 'Merge failed')
    return data
  }, [])

  // Recomputes the merged session for a multi-file section (srs/icd) from its
  // current file list and pushes it into `sessions` / `uploadData`, mirroring
  // exactly what a single /api/upload response used to populate.
  const applyMergedDoc = useCallback(async (type, list) => {
    const merged = list.length ? await mergeSessions(list.map(item => item.session_id), type) : null
    const next = { ...sessionsRef.current, [type]: merged }
    setSessions(next)
    if (type === 'srs') {
      if (merged) {
        setUploadData(prev => ({
          session_id:             merged.session_id,
          icd_session_id:         next.icd?.session_id        || null,
          supporting_session_id:  next.supporting?.session_id || null,
          supporting_session_ids: (prev || {}).supporting_session_ids || [],
        }))
        setTestCases([]); setSummary(null); setError('')
      } else {
        setUploadData(null); setTestCases([]); setSummary(null)
      }
    } else if (type === 'icd') {
      setUploadData(prev => prev ? { ...prev, icd_session_id: merged?.session_id || null } : prev)
    }
  }, [mergeSessions])

  const handleFile = useCallback(async (type, f) => {
    if (!f) return

    // Duplicate check: the same file name must not already exist anywhere —
    // whether in this same section's list (SRS/ICD allow up to 5 docs each)
    // or in one of the other two sections (SRS / ICD / Supporting).
    const normalize = (n) => n.trim().toLowerCase()
    const sectionLists = {
      srs: filesRef.current.srsList || [],
      icd: filesRef.current.icdList || [],
      supporting: filesRef.current.supportingList || [],
    }
    const isDuplicateSameSection = (sectionLists[type] || []).some(item => normalize(item.name) === normalize(f.name))
    const isDuplicate = Object.values(sectionLists).some(
      list => list.some(item => normalize(item.name) === normalize(f.name))
    )
    if (isDuplicate) {
      setDuplicateFile(f.name)
      setDuplicateSameSection(isDuplicateSameSection)
      return
    }

    const ext = '.' + f.name.split('.').pop().toLowerCase()
    if (!ACCEPTED.includes(ext)) {
      setErrors(e => ({ ...e, [type]: `Unsupported: ${ext}` })); return
    }
    // Per-file backstop (the real gate is the batch check in handleFiles below,
    // which runs before any of these individual uploads are even kicked off).
    const maxForType = type === 'supporting' ? MAX_SUPPORTING_DOCS : MAX_DOCS_PER_SECTION
    if (type === 'srs' || type === 'icd' || type === 'supporting') {
      const current = filesRef.current[`${type}List`] || []
      if (current.length >= maxForType) {
        setErrors(e => ({ ...e, [type]: `You are uploading more than ${maxForType} documents. Please upload a maximum of ${maxForType} documents only.` }))
        return
      }
    }
    setErrors(e => ({ ...e, [type]: '' }))
    setLoading(ld => ({ ...ld, [type]: true }))
    const form = new FormData(); form.append('file', f); form.append('doc_type', type)
    try {
      const res  = await fetch('/api/upload', { method: 'POST', body: form })
      const data = await res.json()
      if (!res.ok) throw new Error(data?.detail?.error || 'Upload failed')

      if (type === 'srs' || type === 'icd') {
        const listKey  = `${type}List`
        const newList  = [...(filesRef.current[listKey] || []), { name: f.name, session_id: data.session_id }]
        setFiles(fs => ({ ...fs, [listKey]: newList }))
        await applyMergedDoc(type, newList)
      } else if (type === 'supporting') {
        // Multi-file: append to list — unchanged existing behaviour
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
      }
    } catch (e) {
      setErrors(err => ({ ...err, [type]: e.message }))
    } finally {
      setLoading(ld => ({ ...ld, [type]: false }))
    }
  }, [applyMergedDoc])

  // Batch gate: runs BEFORE any individual upload starts. This is the actual
  // fix — validating count inside handleFile alone doesn't work for a
  // multi-select or multi-drop, because all files in the batch fire against
  // the same pre-update snapshot of filesRef.current in the same tick, so a
  // per-file check can't see files that are "still in flight" from siblings
  // in the same batch. Reject the whole batch atomically instead.
  const handleFiles = useCallback((type, fileList) => {
    const arr = Array.from(fileList || []).filter(Boolean)
    if (arr.length === 0) return

    const max = type === 'supporting' ? MAX_SUPPORTING_DOCS : MAX_DOCS_PER_SECTION
    const currentCount = (filesRef.current[`${type}List`] || []).length

    if (currentCount + arr.length > max) {
      setErrors(e => ({
        ...e,
        [type]: `You are uploading more than ${max} documents. Please upload a maximum of ${max} documents only.`
      }))
      return
    }

    setErrors(e => ({ ...e, [type]: '' }))
    // Process sequentially (not Promise.all) so each upload's state update
    // commits — and filesRef.current updates — before the next one reads it.
    ;(async () => {
      for (const f of arr) {
        await handleFile(type, f)
      }
    })()
  }, [handleFile])

  const handleClear = (type, idx) => {
    if (type === 'supporting' && idx !== undefined) {
      setFiles(fs => ({ ...fs, supportingList: fs.supportingList.filter((_, i) => i !== idx) }))
      return
    }
    if ((type === 'srs' || type === 'icd') && idx !== undefined) {
      const listKey = `${type}List`
      const newList = (filesRef.current[listKey] || []).filter((_, i) => i !== idx)
      setFiles(fs => ({ ...fs, [listKey]: newList }))
      setErrors(e => ({ ...e, [type]: '' }))
      applyMergedDoc(type, newList)
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
          domain:                domain,
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
    setError(''); setTestCases([]); setSummary(null); setControlState('running')
    try {
      const qRes = await fetch('/api/generate/ai', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id:            uploadData.session_id,
          icd_session_id:        uploadData.icd_session_id        || null,
          supporting_session_id: uploadData.supporting_session_id || null,
          selected_req_ids:      scopeConfig.selectedReqIds || null,
          selected_module:       scopeConfig.selectedModule  || null,
          selected_modules:      scopeConfig.selectedModules || null,
          req_prefixes:          reqPrefixes.trim() ? reqPrefixes.split(',').map(p => p.trim()).filter(Boolean) : null,
          review_points:        reviewPoints,
          custom_review_points: customReviewPoints.map(p => p.label),
          domain:               domain,
        }),
      })
      const qData = await qRes.json()
      if (!qRes.ok) { setError(qData?.detail?.suggestion || 'Failed to queue'); return }
      const total = qData.total_chunks ?? 0
      if (!total) { setError('No requirements found.'); return }
      // Generation Checklist items — mirrors exactly what's shown/checked in the
      // Review Checklist panel (built-in points the user left enabled, plus any
      // custom points they added). Rendered as plain instruction sentences under
      // the "Generation Checklist:" header in Step 4 below.
      const activeChecklistPoints = ALL_REVIEW_POINTS.filter(rp => reviewPoints[rp.id])
      const checklistItems = [
        ...activeChecklistPoints.map(rp => `${rp.label} — ${rp.desc}.`),
        ...customReviewPoints.map(p => p.label),
      ]

      // Strategy: for large docs use small batches + save after each.
      // For small docs (<= 30 reqs) do it in one shot.
      const BATCH_SIZE = total > 50 ? 10 : total > 30 ? 15 : total
      const totalBatches = Math.ceil(total / BATCH_SIZE)
      const isMultiBatch = totalBatches > 1

      const step1Lines = isMultiBatch
        ? [
            `This document has ${total} requirements across ${totalBatches} batches of ${BATCH_SIZE}.`,
            `Call tc-tool get_generated_test_cases with batch_index=0, batch_size=${BATCH_SIZE}, then repeat with batch_index=1, 2, 3, ... until is_last_batch=true.`,
          ]
        : [`Call tc-tool get_generated_test_cases with batch_size=${BATCH_SIZE}.`]

      const step3Lines = isMultiBatch
        ? [
            'Generate test cases for the requirements retrieved in the CURRENT batch only. Do NOT accumulate requirements across batches — generate and save one batch at a time.',
            'Ensure coverage of all applicable scenario types, including positive, negative, boundary, exception, and alternate flow scenarios.',
          ]
        : [
            'Generate test cases for all requirements identified in the SRS document.',
            'Ensure coverage of all applicable scenario types, including positive, negative, boundary, exception, and alternate flow scenarios.',
          ]

      const step4Lines = [
        "Incorporate any user-defined instructions provided at runtime through the Generation Checklist. Apply all specified validation criteria, coverage expectations, and generation guidelines in addition to the standard project rules.",
        ...(checklistItems.length > 0
          ? ['', 'Generation Checklist:', ...checklistItems]
          : ['', 'Generation Checklist: none provided for this run — apply the standard project rules only.']),
        ...(reviewPoints.rp6 ? [
          '',
          '⚠ SMART MERGING IS ENABLED — MANDATORY TWO-PHASE PROCESS:',
          'PHASE 1 (do this first): After calling get_generated_test_cases, output a MERGE PLAN showing which requirements you will combine. Example:',
          '  MERGE PLAN: Group A: [REQ_001, REQ_002] - same behaviour | Group B: [REQ_003] - standalone',
          'PHASE 2: Generate test cases following your merge plan.',
          '  - For each group with 2+ requirements: ONE test case with traceability_req_id = "REQ_001, REQ_002"',
          '  - For standalone requirements: generate normally',
          'The NLP context also contains smart_merge_instructions — follow both.',
          'DO NOT generate test cases individually if Smart Merging is enabled.',
        ] : []),
      ]

      const step6Lines = isMultiBatch
        ? [
            "After generating and validating each batch, call tc-tool save_enhanced_test_cases with that batch's test cases (is_partial=True) before moving to the next batch.",
            'For the final batch, call save_enhanced_test_cases with is_partial=False.',
            '⚠ Do NOT wait until all batches are generated to save — a payload over 1MB will fail.',
          ]
        : ['After generating and validating all test cases, call tc-tool save_enhanced_test_cases with the complete set of generated test cases.']

      const prompt = [
        'Generate Test Cases Using tc-tool',
        '',
        'Objective: Generate comprehensive test cases for the uploaded SRS document using tc-tool.',
        '',
        'Step 1 – Retrieve Requirements',
        ...step1Lines,
        '',
        'Step 2 – Apply the Test Case Generation Skill',
        TC_SKILL_INSTRUCTION,
        '',
        'Step 3 – Generate Test Cases',
        ...step3Lines,
        '',
        'Step 4 – Apply Generation Checklist',
        ...step4Lines,
        '',
        'Step 5 – Mandatory Test Case Fields',
        'Every generated test case must include the following attributes: traceability_req_id, test_case_id, scenario_id, inputs (e.g., ["SignalName = Value"]), expected_outcome (e.g., "OutputSignal = Value"), design_methodology, testing_type, scenario_type, priority, objective, preconditions, test_steps, dependent_test_cases, test_environment, remarks, module.',
        `If you can determine it from the SRS/domain pack in use, also include: safety_level ("High"/"Low"), test_level ("Unit"/"Integration"/"System"), standard_reference (e.g. "DO-178C Sec 6.4" or "ISO 26262-6 Table 12"). These are optional per-test-case overrides — if omitted, the tool defaults them from the selected domain ("${domain}").`,
        '',
        'Step 6 – Save Generated Test Cases',
        ...step6Lines,
        '',
        `Total Requirements: ${total}.`,
      ].join('\n')
      // Best-effort fallback only — if this fails silently (focus/permissions),
      // it no longer matters for the automated flow, since the backend now
      // sets the clipboard itself from `prompt` right before pasting.
      await navigator.clipboard.writeText(prompt).catch(() => {})
      setAiWaiting(true)
      setTab('generate')
      // Directly launch Claude Desktop and run the full paste+send automation.
      // (Previously this was gated behind a manual popup + button click.)
      await fetch('/api/open-claude', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt }),
      }).catch(() => {})
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
      <DuplicateDocModal fileName={duplicateFile} sameSection={duplicateSameSection} onClose={() => setDuplicateFile(null)} />

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
            onFiles={handleFiles} onClear={handleClear}
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
            domain={domain} onDomainChange={setDomain}
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
              stage={stage} activityLog={activityLog} requestId={requestId}
              clarification={clarification} onAnswerClarification={answerClarification}
              wsError={wsError} onDismissError={() => setWsError(null)}
              controlState={controlState} onPause={pauseGeneration}
              onResume={resumeGeneration} onStop={stopGeneration}
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