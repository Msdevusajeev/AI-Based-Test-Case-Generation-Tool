import { useState, useEffect } from 'react'

/**
 * ScopeSelector
 * Stores the current scope in a module-level variable (_scope) that is
 * ALWAYS current — no React state batching / stale-closure possible.
 * Also calls onChange(cfg) so the parent can re-render if needed.
 */

// ─── Module-level scope store — lives outside React, always up-to-date ───────
export const _scope = { selectedReqIds: null, selectedModule: null, selectedModules: null }

function setScope(cfg) {
  _scope.selectedReqIds  = cfg.selectedReqIds
  _scope.selectedModule  = cfg.selectedModule
  _scope.selectedModules = cfg.selectedModules || null
  console.log('[SCOPE] _scope updated →', JSON.stringify(_scope))
}
// ─────────────────────────────────────────────────────────────────────────────

export default function ScopeSelector({ sessionId, onChange, reqPrefixes }) {
  const [tab,       setTab]       = useState('all')
  const [reqIds,    setReqIds]    = useState([])
  const [modules,   setModules]   = useState([])
  const [selected,  setSelected]  = useState([])
  const [selModule, setSelModule] = useState('')
  const [selModules, setSelModules] = useState([])
  const [loading,   setLoading]   = useState(true)
  const [err,       setErr]       = useState('')

  const emit = (cfg) => {
    setScope(cfg)           // always-current module variable
    onChange?.(cfg)         // notify parent for UI badge
  }

  useEffect(() => {
    if (!sessionId) return
    setLoading(true); setErr(''); setTab('all')
    const prefixParam = reqPrefixes ? `&req_prefixes=${encodeURIComponent(reqPrefixes)}` : ''
    fetch(`/api/scope?session_id=${sessionId}${prefixParam}`)
      .then(r => { if (!r.ok) throw new Error('Failed to load scope'); return r.json() })
      .then(d => {
        const ids  = d.requirement_ids || []
        const mods = d.modules         || []
        setReqIds(ids); setModules(mods)
        setSelected([...ids]); setSelModule(mods[0] || '')
        setSelModules(mods.length > 0 ? [mods[0]] : [])
        emit({ selectedReqIds: null, selectedModule: null, selectedModules: null })
      })
      .catch(e => setErr(e.message))
      .finally(() => setLoading(false))
  }, [sessionId, reqPrefixes])

  const switchTab = (t) => {
    setTab(t)
    if (t === 'all') {
      emit({ selectedReqIds: null, selectedModule: null })
    } else if (t === 'reqs') {
      const isAll = selected.length === reqIds.length
      emit({ selectedReqIds: isAll ? null : [...selected], selectedModule: null })
    } else if (t === 'module') {
      const mods = selModules.length > 0 ? selModules : (modules.length > 0 ? [modules[0]] : [])
      emit({ selectedReqIds: null, selectedModule: mods[0] || null, selectedModules: mods })
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

  const toggleModule = (mod) => {
    setSelModules(prev => {
      const next = prev.includes(mod) ? prev.filter(m => m !== mod) : [...prev, mod]
      const mods = next.length > 0 ? next : prev  // prevent empty selection
      emit({ selectedReqIds: null, selectedModule: mods[0] || null, selectedModules: mods })
      return mods
    })
  }

  const toggleAllModules = () => {
    const next = selModules.length === modules.length ? [modules[0]] : [...modules]
    setSelModules(next)
    emit({ selectedReqIds: null, selectedModule: next[0] || null, selectedModules: next })
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
            <>
              <div className="flex items-center justify-between mb-2">
                <button onClick={toggleAllModules}
                  className="text-[11px] text-amber/80 underline cursor-pointer">
                  {selModules.length === modules.length ? 'Deselect all' : 'Select all'}
                </button>
                <span className="text-[10px] text-dim font-mono">{selModules.length}/{modules.length}</span>
              </div>
              <div className="space-y-1 max-h-[140px] overflow-y-auto pr-1">
                {modules.map(mod => (
                  <label key={mod} onClick={() => toggleModule(mod)}
                    className={`flex items-center gap-2 px-2 py-1.5 rounded-lg border cursor-pointer
                      transition-all select-none
                      ${selModules.includes(mod)
                        ? 'border-amber/30 bg-amber/8 text-amber'
                        : 'border-border text-dim hover:border-amber/20'}`}>
                    <div className={`w-3.5 h-3.5 rounded border flex items-center justify-center
                      flex-shrink-0 transition-all
                      ${selModules.includes(mod) ? 'bg-amber border-amber' : 'bg-transparent border-border'}`}>
                      {selModules.includes(mod) && <span className="text-bg text-[8px] font-bold">✓</span>}
                    </div>
                    <span className="text-[11px] truncate">{mod}</span>
                  </label>
                ))}
              </div>
              <p className="text-[10px] text-dim mt-2">
                {selModules.length === 1
                  ? <>Only <span className="text-amber">"{selModules[0]}"</span> requirements will be processed</>
                  : <>{selModules.length} modules selected will be processed</>}
              </p>
            </>
          )}
        </>
      )}
    </div>
  )
}
