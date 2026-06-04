import { useState, useEffect } from 'react'

/**
 * ScopeSelector
 * Stores the current scope in a module-level variable (_scope) that is
 * ALWAYS current — no React state batching / stale-closure possible.
 * Also calls onChange(cfg) so the parent can re-render if needed.
 */

// ─── Module-level scope store — lives outside React, always up-to-date ───────
export const _scope = { selectedReqIds: null, selectedModule: null }

function setScope(cfg) {
  _scope.selectedReqIds = cfg.selectedReqIds
  _scope.selectedModule  = cfg.selectedModule
  console.log('[SCOPE] _scope updated →', JSON.stringify(_scope))
}
// ─────────────────────────────────────────────────────────────────────────────

export default function ScopeSelector({ sessionId, onChange }) {
  const [tab,       setTab]       = useState('all')
  const [reqIds,    setReqIds]    = useState([])
  const [modules,   setModules]   = useState([])
  const [selected,  setSelected]  = useState([])
  const [selModule, setSelModule] = useState('')
  const [loading,   setLoading]   = useState(true)
  const [err,       setErr]       = useState('')

  const emit = (cfg) => {
    setScope(cfg)           // always-current module variable
    onChange?.(cfg)         // notify parent for UI badge
  }

  useEffect(() => {
    if (!sessionId) return
    setLoading(true); setErr(''); setTab('all')
    fetch(`/api/scope?session_id=${sessionId}`)
      .then(r => { if (!r.ok) throw new Error('Failed to load scope'); return r.json() })
      .then(d => {
        const ids  = d.requirement_ids || []
        const mods = d.modules         || []
        setReqIds(ids); setModules(mods)
        setSelected([...ids]); setSelModule(mods[0] || '')
        emit({ selectedReqIds: null, selectedModule: null })
      })
      .catch(e => setErr(e.message))
      .finally(() => setLoading(false))
  }, [sessionId])

  const switchTab = (t) => {
    setTab(t)
    if (t === 'all') {
      emit({ selectedReqIds: null, selectedModule: null })
    } else if (t === 'reqs') {
      const isAll = selected.length === reqIds.length
      emit({ selectedReqIds: isAll ? null : [...selected], selectedModule: null })
    } else if (t === 'module') {
      const mod = selModule || modules[0] || null
      emit({ selectedReqIds: null, selectedModule: mod })
    }
  }

  const toggleReq = (rid) => {
    const next = selected.includes(rid)
      ? selected.filter(r => r !== rid)
      : [...selected, rid]
    setSelected(next)
    const isAll = next.length === reqIds.length
    emit({ selectedReqIds: isAll ? null : next, selectedModule: null })
  }

  const toggleAll = () => {
    const next = selected.length === reqIds.length ? [] : [...reqIds]
    setSelected(next)
    const isAll = next.length === reqIds.length
    emit({ selectedReqIds: isAll ? null : next, selectedModule: null })
  }

  const changeModule = (mod) => {
    setSelModule(mod)
    emit({ selectedReqIds: null, selectedModule: mod || null })
  }

  if (loading) return (
    <div className="flex items-center gap-2 py-2">
      <span className="inline-block w-3 h-3 border border-amber border-t-transparent rounded-full spin" />
      <span className="text-xs text-dim">Scanning requirements…</span>
    </div>
  )
  if (err) return <p className="text-xs text-red-400 py-1">⚠ {err}</p>

  return (
    <div>
      <div className="flex gap-1 mb-3">
        {[['all','All'],['reqs','Requirements'],['module','Module']].map(([k,l]) => (
          <button key={k} onClick={() => switchTab(k)}
            className={`flex-1 py-1.5 rounded-lg text-[11px] font-medium border transition-all
              ${tab === k
                ? 'bg-amber/15 border-amber/40 text-amber'
                : 'border-border bg-transparent text-dim hover:border-amber/20 hover:text-text'}`}>
            {l}
          </button>
        ))}
      </div>

      {tab === 'all' && (
        <div className="px-3 py-2.5 rounded-lg bg-amber/5 border border-amber/20">
          <p className="text-[11px] text-amber font-medium">
            All <strong>{reqIds.length}</strong> requirement{reqIds.length !== 1 ? 's' : ''} will be processed
          </p>
          {modules.length > 0 && (
            <p className="text-[10px] text-dim mt-0.5">Modules: {modules.join(', ')}</p>
          )}
        </div>
      )}

      {tab === 'reqs' && (
        <>
          <div className="flex items-center justify-between mb-2">
            <button onClick={toggleAll}
              className="text-[11px] text-amber/80 underline cursor-pointer">
              {selected.length === reqIds.length ? 'Deselect all' : 'Select all'}
            </button>
            <span className="text-[10px] text-dim font-mono">{selected.length}/{reqIds.length}</span>
          </div>
          {selected.length === 0 && (
            <p className="text-[10px] text-red-400 mb-2">⚠ Select at least one requirement</p>
          )}
          <div className="space-y-1 max-h-[140px] overflow-y-auto pr-1">
            {reqIds.map(rid => (
              <label key={rid} onClick={() => toggleReq(rid)}
                className={`flex items-center gap-2 px-2 py-1.5 rounded-lg border cursor-pointer
                  transition-all select-none
                  ${selected.includes(rid)
                    ? 'border-amber/30 bg-amber/8 text-amber'
                    : 'border-border text-dim hover:border-amber/20'}`}>
                <div className={`w-3.5 h-3.5 rounded border flex items-center justify-center
                  flex-shrink-0 transition-all
                  ${selected.includes(rid) ? 'bg-amber border-amber' : 'bg-transparent border-border'}`}>
                  {selected.includes(rid) && <span className="text-bg text-[8px] font-bold">✓</span>}
                </div>
                <span className="text-[11px] font-mono truncate">{rid}</span>
              </label>
            ))}
          </div>
        </>
      )}

      {tab === 'module' && (
        <>
          {modules.length === 0 ? (
            <p className="text-xs text-dim">No modules detected</p>
          ) : (
            <select value={selModule} onChange={e => changeModule(e.target.value)}
              className="w-full bg-card border border-border text-text text-xs rounded-lg
                px-2.5 py-2 focus:outline-none focus:border-amber/50 cursor-pointer">
              {modules.map(m => <option key={m} value={m}>{m}</option>)}
            </select>
          )}
          {selModule && (
            <p className="text-[10px] text-dim mt-2">
              Only <span className="text-amber">"{selModule}"</span> requirements will be processed
            </p>
          )}
        </>
      )}
    </div>
  )
}
