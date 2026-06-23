import re, os, sys

root = os.path.dirname(os.path.abspath(__file__))
f    = os.path.join(root, "frontend", "src", "components", "ResultsTable.jsx")

if not os.path.exists(f):
    print("ERROR: ResultsTable.jsx not found at", f)
    sys.exit(0)

with open(f, "r", encoding="utf-8") as fh:
    s = fh.read()

NEW = """// Col E: Test Details Description
const DETAIL_MAP = {
  normal: 'Verifies the primary activation path. All input conditions set to nominal values confirm the output activates as specified. Baseline for MC/DC tests.',
  boundary: 'Verifies MC/DC independence: one condition varies while others hold at required values, confirming independent output control per DO-178C.',
  edge: 'Verifies all-inactive or conflicting inputs: output must remain safely inactive without unintended activation.',
  robustness: 'Verifies fault tolerance with invalid or missing inputs: no crash, no unsafe output, and recovery tested.',
  transition: 'Verifies state transitions: activation, deactivation, and partial activation sequences are all correct.',
}
function colE(tc) {
  if (tc.test_details_description) return tc.test_details_description
  const sc = (tc.scenario_type || '').toLowerCase()
  const base = DETAIL_MAP[sc] || 'Verifies functional system behaviour as specified.'
  const e = []
  if (tc.design_methodology) e.push('Method: ' + tc.design_methodology)
  if (tc.module) e.push('Module: ' + tc.module)
  return e.length ? base + '\\n' + e.join(' | ') : base
}
"""

s2 = re.sub(
    r'// Col E:.*?^(?=// Col F:)',
    NEW,
    s, count=1, flags=re.DOTALL | re.MULTILINE
)

with open(f, "w", encoding="utf-8") as fh:
    fh.write(s2)

changed = s2 != s
print("Patched OK, changed=" + str(changed))
