import { useState, useMemo } from 'react'

// ─── COLUMN DEFINITIONS ────────────────────────────────────────────────────
// Standardized Test Case Template — 19 mandatory columns, fixed order.
// Columns marked `derived: true` are computed server-side (see
// output_generator.compute_gui_display_fields /
// compute_standard_template_fields) and attached to each test case before
// it reaches the GUI. Do NOT re-derive these in JS — see the note below.
const COLUMNS = [
  { key: 'traceability_req_id',    label: 'Requirement_ID',       width: 160 },
  { key: 'tc_id_display',          label: 'TC_ID',                width: 150, derived: true },
  { key: 'objective',              label: 'Test Objective',       width: 260 },
  { key: 'test_details_description', label: 'Test Details Description', width: 280, derived: true },
  { key: 'test_precondition_display', label: 'Test Pre-Condition', width: 300, derived: true },
  { key: 'inputs_display',         label: 'Inputs',               width: 240, derived: true },
  { key: 'test_steps',             label: 'Test Steps',           width: 280 },
  { key: 'requirement_type_display', label: 'Requirement_Type',   width: 130, derived: true },
  { key: 'coverage_type_display',  label: 'Coverage_Type',        width: 120, derived: true },
  { key: 'test_level_display',     label: 'Test_Level',           width: 110, derived: true },
  { key: 'scenario_type_display',  label: 'Scenario_Type',        width: 120, derived: true },
  { key: 'outputs_display',        label: 'Expected Outputs',     width: 220, derived: true },
  { key: 'module_display',         label: 'Module',               width: 130, derived: true },
  { key: 'safety_level_display',   label: 'Safety_Level',         width: 100, derived: true },
  { key: 'priority',               label: 'Priority',             width: 90  },
  { key: 'pass_fail_criteria',     label: 'PASS/FAIL Criteria',   width: 320, derived: true },
  { key: 'configure_baseline',     label: 'Configure_Baseline',   width: 140, derived: true },
  { key: 'remarks_display',        label: 'Remarks',              width: 320, derived: true },
  { key: 'standard_reference_display', label: 'Standard_Reference', width: 150, derived: true },
]

// ─── HELPERS ───────────────────────────────────────────────────────────────
function moduleAlphaOnly(module) {
  const cleaned = (module || '').replace(/[^A-Za-z\s]/g, '').replace(/\s+/g, ' ').trim()
  return cleaned || 'General'
}

// ─── DERIVED COLUMNS ─────────────────────────────────────────────────────────
// Every derived column below is computed by the BACKEND
// (output_generator.compute_gui_display_fields /
// compute_standard_template_fields) and attached to each test case as
// tc_id_display / test_details_description / test_precondition_display /
// inputs_display / requirement_type_display / coverage_type_display /
// test_level_display / scenario_type_display / outputs_display /
// module_display / safety_level_display / pass_fail_criteria /
// configure_baseline / remarks_display / standard_reference_display —
// the exact same text written into the Excel/Word export.
//
// This file must not re-derive any of these independently in JS (that's
// what caused the GUI/Excel drift the backend fields exist to fix). If a
// column is missing or wrong, fix the backend function so it's correct in
// both places at once. The fallbacks below only cover test cases the
// backend hasn't attached fields to yet (e.g. mid-stream MCP results).

function tcId(tc) {
  if (tc.tc_id_display) return tc.tc_id_display
  const a = tc.test_case_id || '', b = tc.scenario_id || ''
  return a && b ? `${a}_${b}` : (a || b || '—')
}

function colDetails(tc) {
  return tc.test_details_description || 'Verifies functional system behaviour as specified in the requirement.'
}

function colPrecondition(tc) {
  return tc.test_precondition_display || ''
}

function colInputs(tc) {
  return tc.inputs_display || (Array.isArray(tc.inputs) ? tc.inputs.join('; ') : '')
}

function colOutputs(tc) {
  return tc.outputs_display || (tc.expected_outcome || '').split('.')[0].trim()
}

function colModule(tc) {
  return tc.module_display || moduleAlphaOnly(tc.module)
}

function colRemarks(tc) {
  return tc.remarks_display || ''
}

function colReqType(tc) {
  return tc.requirement_type_display || ((tc.requirement_type || '').startsWith('non') ? 'Non-Functional' : 'Functional')
}

function colCoverageType(tc) {
  if (tc.coverage_type_display) return tc.coverage_type_display
  const map = { verification: 'Verification', validation: 'Validation', integration: 'Integration' }
  return map[(tc.testing_type || '').toLowerCase()] || 'Verification'
}

function colTestLevel(tc) {
  return tc.test_level_display || 'System'
}

function colScenarioType(tc) {
  if (tc.scenario_type_display) return tc.scenario_type_display
  return (tc.scenario_type || 'normal').split('_').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join('')
}

function colSafetyLevel(tc) {
  return tc.safety_level_display || tc.safety_level || '—'
}

function colPassFail(tc) {
  return tc.pass_fail_criteria || ''
}

function colStandardRef(tc) {
  return tc.standard_reference_display || tc.standard_reference || '—'
}

// ─── BADGE ──────────────────────────────────────────────────────────────────
const BADGE_MAP = {
  coverage_type_display: { Verification: 'badge-verification', Validation: 'badge-validation', Integration: 'badge-integration' },
  scenario_type_display: { Normal: 'badge-normal', Boundary: 'badge-boundary', Edge: 'badge-edge', Robustness: 'badge-robustness', InvalidInput: 'badge-invalid_input' },
  safety_level_display:  { High: 'badge-robustness', Low: 'badge-normal' },
}

const SCENARIO_INLINE = {
  Transition: 'bg-purple-500/15 text-purple-400 border border-purple-500/30',
  Fault:      'bg-red-500/15 text-red-400 border border-red-500/30',
  Timing:     'bg-blue-500/15 text-blue-400 border border-blue-500/30',
  BeyondRange:'bg-orange-500/15 text-orange-400 border border-orange-500/30',
  Mcdc:       'bg-teal-500/15 text-teal-400 border border-teal-500/30',
}

function Badge({ type, value }) {
  const cls    = BADGE_MAP[type]?.[value]
  const inline = type === 'scenario_type_display' ? SCENARIO_INLINE[value] : null
  if (!cls && !inline) return <span className="text-xs text-dim">{value || '—'}</span>
  return <span className={`${cls || inline} text-[10px] font-mono px-1.5 py-0.5 rounded`}>{value}</span>
}

// ─── CELL RENDERER ──────────────────────────────────────────────────────────
const TEXT_RENDERERS = {
  test_details_description:    colDetails,
  test_precondition_display:   colPrecondition,
  inputs_display:               colInputs,
  outputs_display:              colOutputs,
  module_display:                colModule,
  remarks_display:                colRemarks,
  pass_fail_criteria:             colPassFail,
}

function CellValue({ col, tc }) {
  const key = col.key

  if (key === 'tc_id_display') {
    return <span className="font-mono text-[11px] text-amber/90">{tcId(tc)}</span>
  }

  if (key === 'standard_reference_display') {
    return <span className="text-[11px] text-dim">{colStandardRef(tc)}</span>
  }

  if (key === 'requirement_type_display') {
    return <span className="text-xs text-dim">{colReqType(tc)}</span>
  }
  if (key === 'coverage_type_display') {
    return <Badge type={key} value={colCoverageType(tc)} />
  }
  if (key === 'test_level_display') {
    return <span className="text-xs text-dim">{colTestLevel(tc)}</span>
  }
  if (key === 'scenario_type_display') {
    return <Badge type={key} value={colScenarioType(tc)} />
  }
  if (key === 'safety_level_display') {
    return <Badge type={key} value={colSafetyLevel(tc)} />
  }

  if (key in TEXT_RENDERERS) {
    const text = TEXT_RENDERERS[key](tc)
    return text
      ? <span className="text-[11px] text-dim leading-snug whitespace-pre-wrap">{text}</span>
      : <span className="text-dim/40 text-xs italic">—</span>
  }

  if (key === 'configure_baseline') {
    const text = tc.configure_baseline
    return text
      ? <span className="text-[11px] text-dim">{text}</span>
      : <span className="text-dim/40 text-xs italic">—</span>
  }

  const value = tc[key]

  if (key === 'priority' || key === 'traceability_req_id') {
    return <span className="font-mono text-[11px] text-amber/90">{value || '—'}</span>
  }

  if (Array.isArray(value)) {
    if (!value.length) return <span className="text-dim/40 text-xs italic">—</span>
    return (
      <ol className="space-y-1 list-none m-0 p-0">
        {value.map((v, i) => (
          <li key={i} className="text-[11px] text-dim leading-snug">{v}</li>
        ))}
      </ol>
    )
  }

  if (!value) return <span className="text-dim/40 text-xs italic">—</span>
  return <span className="text-[11px] text-dim leading-snug whitespace-pre-wrap">{value}</span>
}

// ─── HELPERS ────────────────────────────────────────────────────────────────
function unique(arr) {
  return ['All', ...Array.from(new Set(arr.filter(Boolean))).sort()]
}

const totalWidth = COLUMNS.reduce((s, c) => s + c.width, 0)

// ─── MAIN COMPONENT ─────────────────────────────────────────────────────────
export default function ResultsTable({ testCases }) {
  const [filters, setFilters] = useState({
    requirement_id:   'All',
    module:           'All',
    priority:         'All',
    scenario_type:    'All',
    testing_type:     'All',
    requirement_type: 'All',
  })
  const [search, setSearch] = useState('')
  const [page,   setPage]   = useState(1)
  const PAGE_SIZE = 50

  const opts = useMemo(() => ({
    requirement_id:   unique(testCases.map(t => t.traceability_req_id)),
    module:           unique(testCases.map(t => colModule(t))),
    priority:         unique(testCases.map(t => t.priority)),
    scenario_type:    unique(testCases.map(t => colScenarioType(t))),
    testing_type:     unique(testCases.map(t => colCoverageType(t))),
    requirement_type: unique(testCases.map(t => colReqType(t))),
  }), [testCases])

  const filtered = useMemo(() => {
    const q = search.toLowerCase()
    return testCases.filter(tc => {
      const mod = colModule(tc)
      if (filters.requirement_id   !== 'All' && tc.traceability_req_id !== filters.requirement_id)   return false
      if (filters.module           !== 'All' && mod                    !== filters.module)             return false
      if (filters.priority         !== 'All' && tc.priority            !== filters.priority)           return false
      if (filters.scenario_type    !== 'All' && colScenarioType(tc)    !== filters.scenario_type)      return false
      if (filters.testing_type     !== 'All' && colCoverageType(tc)    !== filters.testing_type)       return false
      if (filters.requirement_type !== 'All' && colReqType(tc)         !== filters.requirement_type)   return false
      if (q && !JSON.stringify(tc).toLowerCase().includes(q))                                          return false
      return true
    })
  }, [testCases, filters, search])

  const totalPages = Math.ceil(filtered.length / PAGE_SIZE)
  const paged      = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE)
  const setFilter  = (k, v) => { setFilters(f => ({ ...f, [k]: v })); setPage(1) }

  function FilterSelect({ k, label }) {
    return (
      <div className="flex flex-col gap-1">
        <label className="text-[10px] text-muted font-mono uppercase tracking-widest">{label}</label>
        <select
          value={filters[k]}
          onChange={e => setFilter(k, e.target.value)}
          className="bg-card border border-border text-dim text-xs rounded-lg px-2.5 py-1.5 focus:outline-none focus:border-amber/50 cursor-pointer"
        >
          {opts[k].map(o => <option key={o} value={o}>{o}</option>)}
        </select>
      </div>
    )
  }

  return (
    <div className="fade-in space-y-4">

      {/* Title */}
      <div className="flex items-center gap-3">
        <div className="w-7 h-7 rounded bg-amber/10 border border-amber/30 flex items-center justify-center text-amber text-sm font-mono font-bold">4</div>
        <h2 className="text-base font-semibold text-text">
          Test Cases
          <span className="ml-2 font-mono text-xs text-muted">
            {filtered.length} / {testCases.length}
          </span>
        </h2>
      </div>

      {/* Filters */}
      <div className="bg-card border border-border rounded-xl p-4">
        <div className="flex flex-wrap gap-4 items-end">
          <div className="flex flex-col gap-1 flex-1 min-w-[160px]">
            <label className="text-[10px] text-muted font-mono uppercase tracking-widest">Search</label>
            <input
              type="text"
              placeholder="Search any field…"
              value={search}
              onChange={e => { setSearch(e.target.value); setPage(1) }}
              className="bg-surface border border-border text-dim text-xs rounded-lg px-3 py-1.5 focus:outline-none focus:border-amber/50"
            />
          </div>
          <FilterSelect k="requirement_id"   label="Req ID" />
          <FilterSelect k="module"           label="Module" />
          <FilterSelect k="scenario_type"    label="Scenario Type" />
          <FilterSelect k="testing_type"     label="Coverage Type" />
          <button
            onClick={() => {
              setFilters({ requirement_id: 'All', module: 'All', priority: 'All', scenario_type: 'All', testing_type: 'All', requirement_type: 'All' })
              setSearch(''); setPage(1)
            }}
            className="text-xs text-muted hover:text-amber transition-colors self-end pb-1.5"
          >
            Clear
          </button>
        </div>
      </div>

      {/* Table */}
      <div className="rounded-xl border border-border overflow-auto" style={{ maxHeight: '65vh' }}>
        <table className="w-full border-collapse" style={{ minWidth: totalWidth }}>
          <thead>
            <tr>
              {COLUMNS.map(col => (
                <th key={col.key} className="tc-header" style={{ minWidth: col.width }}>
                  {col.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {paged.map((tc, rowIdx) => (
              <tr
                key={tcId(tc) + rowIdx}
                className={`transition-colors hover:bg-surface/60 ${rowIdx % 2 === 0 ? 'bg-transparent' : 'bg-surface/30'}`}
              >
                {COLUMNS.map(col => (
                  <td key={col.key} className="tc-cell" style={{ minWidth: col.width }}>
                    <CellValue col={col} tc={tc} />
                  </td>
                ))}
              </tr>
            ))}
            {paged.length === 0 && (
              <tr>
                <td colSpan={COLUMNS.length} className="tc-cell text-center text-muted py-12">
                  No test cases match the current filters.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between">
          <p className="text-xs text-dim font-mono">
            Page {page} of {totalPages} · showing {(page-1)*PAGE_SIZE+1}–{Math.min(page*PAGE_SIZE, filtered.length)} of {filtered.length}
          </p>
          <div className="flex gap-2">
            <button
              disabled={page === 1}
              onClick={() => setPage(p => p - 1)}
              className="px-3 py-1 text-xs rounded-lg border border-border text-dim hover:border-amber/50 hover:text-amber disabled:opacity-30 disabled:cursor-not-allowed transition-all"
            >
              ← Prev
            </button>
            <button
              disabled={page === totalPages}
              onClick={() => setPage(p => p + 1)}
              className="px-3 py-1 text-xs rounded-lg border border-border text-dim hover:border-amber/50 hover:text-amber disabled:opacity-30 disabled:cursor-not-allowed transition-all"
            >
              Next →
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
