import { useState, useRef, useEffect } from 'react'

const REVIEW_POINTS = [
  {
    id: 'rp1',
    label: 'Segregate by Module & Requirement Type',
    desc: 'Detect modules and classify functional vs non-functional',
  },
  {
    id: 'rp2',
    label: 'Full Scenario Coverage',
    desc: 'Generate Normal, Boundary, Edge, and Robustness scenarios',
  },
  {
    id: 'rp3',
    label: 'Map to Testing Type',
    desc: 'Assign Verification, Validation, or Integration per requirement',
  },
  {
    id: 'rp4',
    label: 'Rule-Based Remarks',
    desc: 'Auto-detect risks, PCI concerns, and missing specs',
  },
]

export default function ReviewPointsPanel({
  reviewPoints, onChange, disabled,
  customPoints, onCustomPointsChange,
}) {
  const [showInput, setShowInput] = useState(false)
  const [inputVal,  setInputVal]  = useState('')
  const inputRef = useRef(null)

  useEffect(() => {
    if (showInput && inputRef.current) inputRef.current.focus()
  }, [showInput])

  const handleAdd = () => {
    const trimmed = inputVal.trim()
    if (!trimmed) { setShowInput(false); setInputVal(''); return }
    onCustomPointsChange([...customPoints, {
      id: `custom_${Date.now()}`, label: trimmed, desc: 'Custom review point',
    }])
    setInputVal('')
    setShowInput(false)
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter')  handleAdd()
    if (e.key === 'Escape') { setShowInput(false); setInputVal('') }
  }

  return (
    <div>

      {/* ── Built-in review points ── */}
      <div className="space-y-1.5 mb-3">
        {REVIEW_POINTS.map((rp) => {
          const enabled = reviewPoints[rp.id]
          return (
            <label key={rp.id}
              className={`flex items-start gap-2.5 p-2.5 rounded-lg border cursor-pointer transition-all
                ${enabled ? 'border-amber/25 bg-amber/5' : 'border-border bg-transparent'}
                ${disabled ? 'opacity-50 cursor-not-allowed' : 'hover:border-amber/30'}`}>
              <div className="mt-0.5 flex-shrink-0">
                <div className={`w-[15px] h-[15px] rounded border flex items-center justify-center transition-all
                  ${enabled ? 'bg-amber border-amber' : 'bg-transparent border-border'}`}>
                  {enabled && <span className="text-bg text-[9px] font-bold leading-none">✓</span>}
                </div>
              </div>
              <input type="checkbox" className="hidden" checked={enabled} disabled={disabled}
                onChange={() => !disabled && onChange(rp.id, !enabled)} />
              <div className="flex-1 min-w-0">
                <span className="text-xs font-medium text-text">{rp.label}</span>
                <p className="text-[11px] text-dim mt-0.5 leading-relaxed">{rp.desc}</p>
              </div>
            </label>
          )
        })}
      </div>

      {/* ── Custom review points ── */}
      {customPoints.length > 0 && (
        <div className="space-y-1.5 mb-3">
          {customPoints.map((cp) => (
            <div key={cp.id}
              className="flex items-center gap-2.5 px-2.5 py-2 rounded-lg border border-amber/30
                bg-amber/8 group">
              <div className="w-[15px] h-[15px] rounded border bg-amber border-amber
                flex items-center justify-center flex-shrink-0">
                <span className="text-bg text-[9px] font-bold leading-none">✓</span>
              </div>
              <span className="flex-1 text-xs font-medium text-amber truncate">{cp.label}</span>
              {!disabled && (
                <button onClick={() => onCustomPointsChange(customPoints.filter(p => p.id !== cp.id))}
                  title="Remove"
                  className="flex-shrink-0 w-5 h-5 rounded flex items-center justify-center
                    text-dim hover:text-red-400 hover:bg-red-500/10 transition-all text-xs">
                  ✕
                </button>
              )}
            </div>
          ))}
        </div>
      )}

      {/* ── Add custom review point ── */}
      {!disabled && (
        showInput ? (
          /* Expanded input */
          <div className="mb-3 rounded-xl border border-amber/40 bg-amber/5 overflow-hidden">
            <div className="flex items-center gap-2 px-3 py-2 border-b border-amber/20">
              <span className="text-amber text-xs">✦</span>
              <span className="text-xs font-medium text-amber">New review point</span>
              <button onClick={() => { setShowInput(false); setInputVal('') }}
                className="ml-auto text-dim hover:text-text text-xs w-5 h-5 flex items-center
                  justify-center rounded hover:bg-surface transition-colors">
                ✕
              </button>
            </div>
            <div className="p-2.5 flex items-center gap-2">
              <input
                ref={inputRef}
                type="text"
                value={inputVal}
                onChange={e => setInputVal(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="e.g. Verify signal range limits…"
                maxLength={120}
                className="flex-1 min-w-0 bg-transparent text-xs text-text
                  placeholder-dim/50 outline-none border-b border-amber/30
                  pb-1 focus:border-amber transition-colors"
              />
              <button onClick={handleAdd} disabled={!inputVal.trim()}
                className={`flex-shrink-0 px-3 py-1.5 rounded-lg text-[11px] font-semibold
                  transition-all
                  ${inputVal.trim()
                    ? 'bg-amber text-bg hover:bg-amber/90 cursor-pointer shadow-sm shadow-amber/20'
                    : 'bg-border text-dim cursor-not-allowed'}`}>
                Add
              </button>
            </div>
            <p className="px-3 pb-2 text-[10px] text-dim/70">
              Press Enter to add · Esc to cancel
            </p>
          </div>
        ) : (
          /* Collapsed — prominent dashed button */
          <button
            onClick={() => setShowInput(true)}
            className="w-full mb-3 flex items-center justify-center gap-2 px-3 py-2.5
              rounded-xl border-2 border-dashed border-amber/30 text-amber/70
              hover:border-amber hover:text-amber hover:bg-amber/5
              transition-all group cursor-pointer">
            <span className="w-5 h-5 rounded-full border border-amber/50 group-hover:border-amber
              flex items-center justify-center text-xs font-bold transition-all
              group-hover:bg-amber group-hover:text-bg">
              +
            </span>
            <span className="text-xs font-medium">Add customised prompts</span>
          </button>
        )
      )}

      {/* ── Divider ── */}
      <div className="border-t border-border my-2" />

      {/* ── Remove duplicates — visually distinct ── */}
      <label
        className={`flex items-start gap-2.5 p-2.5 rounded-lg border cursor-pointer transition-all
          ${reviewPoints.rp5
            ? 'border-red-500/30 bg-red-500/8'
            : 'border-border bg-transparent'}
          ${disabled ? 'opacity-50 cursor-not-allowed' : 'hover:border-red-500/30'}`}>
        <div className="mt-0.5 flex-shrink-0">
          <div className={`w-[15px] h-[15px] rounded border flex items-center justify-center
            transition-all
            ${reviewPoints.rp5 ? 'bg-red-500 border-red-500' : 'bg-transparent border-border'}`}>
            {reviewPoints.rp5 && <span className="text-white text-[9px] font-bold leading-none">✓</span>}
          </div>
        </div>
        <input type="checkbox" className="hidden" checked={reviewPoints.rp5} disabled={disabled}
          onChange={() => !disabled && onChange('rp5', !reviewPoints.rp5)} />
        <div className="flex-1 min-w-0">
          <span className="text-xs font-medium text-red-400">Remove duplicate test cases</span>
          <p className="text-[11px] text-dim mt-0.5 leading-relaxed">
            Removes near-identical TCs after generation (similarity ≥ 0.85)
          </p>
        </div>
        <span className="text-red-400/60 text-xs flex-shrink-0 mt-0.5">⊘</span>
      </label>
    </div>
  )
}
