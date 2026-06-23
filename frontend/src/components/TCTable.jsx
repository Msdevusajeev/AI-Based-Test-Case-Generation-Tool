import { useState, useMemo } from 'react'

// ─── COLUMN DEFINITIONS ────────────────────────────────────────────────────
const COLUMNS = [
  { key: 'traceability_req_id',  label: 'Requirement_ID',                width: 160 },
  { key: 'test_case_id',         label: 'TC_ID',                         width: 120 },
  { key: 'scenario_id',          label: 'Scenario No',                   width: 100 },
  { key: 'objective',            label: 'Test Objective',                 width: 280 },
  { key: '_col_e',               label: 'Test Details Description',       width: 280 },
  { key: '_col_f',               label: 'Test Precondition',              width: 320 },
  { key: 'inputs',               label: 'Inputs',                         width: 260 },
  { key: 'test_steps',           label: 'Test Steps',                     width: 280 },
  { key: '_col_i',               label: 'Expected Outputs',               width: 220 },
  { key: '_col_j',               label: 'Depands On',                     width: 160 },
  { key: 'test_environment',     label: 'Test_Env',                       width: 90  },
  { key: 'testing_type',         label: 'Test_Type',                      width: 120 },
  { key: 'scenario_type',        label: 'Scenario_Type',                  width: 110 },
  { key: '_col_n',               label: 'Remarks/Additional information', width: 320 },
  { key: '_col_o',               label: 'Module',                         width: 130 },
]

// ─── HELPERS ───────────────────────────────────────────────────────────────
function listToStr(val) {
  if (Array.isArray(val)) return val.filter(Boolean).join('\n')
  return val ? String(val) : ''
}

function cap(s) { return s ? s.charAt(0).toUpperCase() + s.slice(1) : '' }

function moduleAlphaOnly(module) {
  const cleaned = (module || '').replace(/[^A-Za-z\s]/g, '').replace(/\s+/g, ' ').trim()
  return cleaned || 'General'
}

function parseSignalValue(entry) {
  const m = /^(.+?)[:\s]*[=:]\s*(.+)$/.exec((entry || '').trim())
  if (m) return [m[1].trim(), m[2].trim()]
  return [entry.trim(), entry.trim()]
}

// ─── COLUMN E: Test Details Description ────────────────────────────────────
// Narrative description of what the test does — scenario-type driven.
// Matches output_generator.py _col_e_test_details exactly.
const DETAIL_MAP = {
  normal: (
    'Verifies the primary activation path. All input conditions are set to their ' +
    'nominal required values simultaneously to confirm the system output activates ' +
    'as specified. This scenario also serves as the baseline reference for all ' +
    'MC/DC independence pair tests.'
  ),
  boundary: (
    'Verifies MC/DC independence by varying exactly one input condition at a time ' +
    'while holding all other conditions at their required values. Confirms the ' +
    'output state change is solely and independently controlled by the varied ' +
    'condition, satisfying the MC/DC coverage criterion per DO-178C.'
  ),
  edge: (
    'Verifies system behaviour when all input conditions are simultaneously ' +
    'inactive, conflicting, or at non-activating values. Confirms the output ' +
    'remains in its safe inactive state and the system correctly handles this ' +
    'configuration without any unintended activation.'
  ),
  robustness: (
    'Verifies system stability and fault tolerance when inputs receive invalid, ' +
    'out-of-range, or unavailable values. Confirms the system does not crash, ' +
    'produce undefined outputs, or enter an unsafe state. Also tests recovery ' +
    'behaviour when inputs return to valid range.'
  ),
  transition: (
    'Verifies correct state transition behaviour as the system moves between ' +
    'active and inactive states. Confirms output activation and deactivation ' +
    'sequences are correct, partial activation conditions are handled properly, ' +
    'and state changes occur at the expected trigger points.'
  ),
}

function colE(tc) {
  const sc   = (tc.scenario_type || '').toLowerCase()
  const base = DETAIL_MAP[sc] || 'Verifies functional system behaviour as specified in the requirement.'
  const extra = []
  if (tc.design_methodology) extra.push(`Design methodology: ${tc.design_methodology}.`)
  if (tc.module)             extra.push(`Module under test: ${tc.module}.`)
  return extra.length ? base + '\n' + extra.join('  ') : base
}

// ─── COLUMN F: Test Precondition ────────────────────────────────────────────
function colF(tc) {
  if (!tc.preconditions || !tc.preconditions.length) return ''
  return listToStr(tc.preconditions)
}

// ─── COLUMN I: Expected Outputs ─────────────────────────────────────────────
function colI(tc) {
  const raw = tc.expected_outcome || ''
  if (!raw) return ''
  return raw.split('.')[0].trim()
}

// ─── COLUMN J: Depends On ───────────────────────────────────────────────────
function colJ(tc) {
  const raw = (tc.dependent_test_cases || 'None').trim()
  if (/_SC-\d{3}$/.test(raw)) return raw
  if (/_SC_\d{3}$/.test(raw)) return raw
  if (raw.toLowerCase() === 'none') return 'None'
  return `${tc.test_case_id}_SC-001`
}

// ─── COLUMN N: Remarks ──────────────────────────────────────────────────────
function colN(tc) {
  const bullets = []
  bullets.push(`• Testing Type: ${cap(tc.testing_type)} | Scenario Type: ${cap(tc.scenario_type)}`)

  const scWhat = {
    normal:     'All input values set to normal/valid values; correct system output is verified.',
    boundary:   'Input boundary values tested: minimum, maximum, min-1, max+1 for each parameter.',
    edge:       'Edge case conditions tested (state transitions, simultaneous changes, unusual-but-valid states).',
    robustness: 'Invalid/out-of-range input values tested; system must respond safely without crash.',
    transition: 'State transitions tested: Inactive→Active, Active→Inactive, and partial activation sequences.',
  }
  bullets.push(`• What is tested: ${scWhat[tc.scenario_type] || 'Functional system behaviour verified.'}`)

  for (const entry of (tc.inputs || [])) {
    const [name, value] = parseSignalValue(entry)
    if (!name || !value) continue
    const nl = name.toLowerCase()
    if (['test environment', 'all prerequisite', 'sub-requirements'].includes(nl)) continue
    const vl = value.toLowerCase()
    if (tc.scenario_type === 'boundary') {
      if (vl.includes('max') || vl.includes('maximum'))
        bullets.push(`• ${name}: maximum value is tested`)
      else if (vl.includes('min') || vl.includes('minimum'))
        bullets.push(`• ${name}: minimum value is tested`)
      else
        bullets.push(`• ${name}: boundary value '${value}' is tested`)
    } else if (tc.scenario_type === 'edge') {
      bullets.push(`• ${name}: edge-case value '${value}' is tested`)
    } else if (tc.scenario_type === 'robustness') {
      bullets.push(`• ${name}: invalid/out-of-range value '${value}' is tested`)
    } else if (tc.scenario_type === 'transition') {
      bullets.push(`• ${name}: transitions to/from '${value}' — state change verified`)
    }
  }

  const inputsRaw = listToStr(tc.inputs).toLowerCase()
  if (['icd', 'derived', 'interface'].some(kw => inputsRaw.includes(kw))) {
    bullets.push('• Input source: Values derived from ICD document (not explicitly defined in SRS).')
  } else {
    bullets.push('• Input source: Input values explicitly defined in SRS specification.')
  }

  if (tc.remarks) {
    const rawParts = tc.remarks.split(/\s*[|\n•]+\s*/).filter(Boolean)
    for (const part of rawParts) {
      const p = part.trim()
      if (!p) continue
      if (/test\s+basis|input\s+values\s+derived\s+from\s+srs|srs\s+requirement\s+\w/i.test(p)) continue
      if (/enum|sub.req|note|reference|derived from icd|document context/i.test(p)) {
        bullets.push(`• ${p}`)
      }
    }
  }

  return bullets.join('\n')   // ← was missing
}                              // ← was missing (closing brace for colN)

// ─── COLUMN O: Module ───────────────────────────────────────────────────────
function colO(tc) { return moduleAlphaOnly(tc.module) }

// ─── BADGE ──────────────────────────────────────────────────────────────────
const BADGE_MAP = {
  testing_type:     { verification: 'badge-verification', validation: 'badge-validation', integration: 'badge-integration' },
  scenario_type:    { normal: 'badge-normal', boundary: 'badge-boundary', edge: 'badge-edge', robustness: 'badge-robustness' },
  test_environment: { Dev: 'badge-normal', QA: 'badge-boundary', UAT: 'badge-validation', Prod: 'badge-robustness' },
}

const SCENARIO_INLINE = {
  transition: 'bg-purple-500/15 text-purple-400 border border-purple-500/30',
}

function Badge({ type, value }) {
  const cls    = BADGE_MAP[type]?.[value]
  const inline = type === 'scenario_type' ? SCENARIO_INLINE[value] : null
  if (!cls && !inline) return <span className="text-xs text-dim">{value || '—'}</span>
  return <span className={`${cls || inline} text-[10px] font-mono px-1.5 py-0.5 rounded`}>{value}</span>
}

// ─── CELL RENDERER ──────────────────────────────────────────────────────────
function CellValue({ col, tc }) {
  const key = col.key

  if (key === '_col_e') {
    const text = colE(tc)
    return <span className="text-[11px] text-dim leading-snug whitespace-pre-wrap">{text}</span>
  }

  if (key === '_col_f') {
    const text = colF(tc)
    return text
      ? <span className="text-[11px] text-dim leading-snug whitespace-pre-wrap">{text}</span>
      : <span className="text-dim/40 text-xs italic">—</span>
  }

  if (key === '_col_i') {
    const text = colI(tc)
    return text
      ? <span className="text-[11px] text-dim leading-snug whitespace-pre-wrap">{text}</span>
      : <span className="text-dim/40 text-xs italic">—</span>
  }

  if (key === '_col_j') {
    const dep = colJ(tc)
    return dep === 'None'
      ? <span className="text-xs text-dim/50 italic">None</span>
      : <span className="font-mono text-[11px] text-amber/90">{dep}</span>
  }

  if (key === '_col_n') {
    const text = colN(tc)
    return text
      ? <span className="text-[11px] text-dim leading-snug whitespace-pre-wrap">{text}</span>
      : <span className="text-dim/40 text-xs italic">—</span>
  }

  if (key === '_col_o') {
    return <span className="text-[11px] text-dim">{colO(tc)}</span>
  }

  const value = tc[key]

  if (['test_environment', 'testing_type', 'scenario_type'].includes(key)) {
    return <Badge type={key} value={value} />
  }

  if (['traceability_req_id', 'test_case_id', 'scenario_id'].includes(key)) {
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
    module:           unique(testCases.map(t => moduleAlphaOnly(t.module))),
    priority:         unique(testCases.map(t => t.priority)),
    scenario_type:    unique(testCases.map(t => t.scenario_type)),
    testing_type:     unique(testCases.map(t => t.testing_type)),
    requirement_type: unique(testCases.map(t => t.requirement_type)),
  }), [testCases])

  const filtered = useMemo(() => {
    const q = search.toLowerCase()
    return testCases.filter(tc => {
      const mod = moduleAlphaOnly(tc.module)
      if (filters.requirement_id   !== 'All' && tc.traceability_req_id !== filters.requirement_id)   return false
      if (filters.module           !== 'All' && mod                    !== filters.module)             return false
      if (filters.priority         !== 'All' && tc.priority            !== filters.priority)           return false
      if (filters.scenario_type    !== 'All' && tc.scenario_type       !== filters.scenario_type)      return false
      if (filters.testing_type     !== 'All' && tc.testing_type        !== filters.testing_type)       return false
      if (filters.requirement_type !== 'All' && tc.requirement_type    !== filters.requirement_type)   return false
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
          <FilterSelect k="priority"         label="Priority" />
          <FilterSelect k="scenario_type"    label="Scenario" />
          <FilterSelect k="testing_type"     label="Testing Type" />
          <FilterSelect k="requirement_type" label="Req Type" />
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
                key={tc.test_case_id + tc.scenario_id + rowIdx}
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
