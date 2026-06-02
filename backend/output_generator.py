"""
output_generator.py
Generates Excel output strictly matching One_TC_Updated.xlsx template format.

Exact column layout (matches template):
  A(1)   Requirement_ID
  B(2)   TC_ID
  C(3)   Scenario No          -- format: SC_001, SC_002 ...
  D(4)   Test Objective
  E(5)   Test Details Description
  F(6)   Test Precondition     -- Req 5: consolidates E + input-related Test Steps from H col
  G(7)   Inputs               -- merged header over sub-signal columns H, I, ...
  H(8)+  [input signal sub-columns, dynamic]
  J(10)  Test Steps           -- standalone column (after input sub-cols)
  K(11)  Expected Outputs     -- merged header over output signal sub-columns
  L(12)+ [output signal sub-columns, dynamic]
  M(13)  Depands On           -- TC_ID + Scenario No concatenated (Req 10)
  N(14)  Test_Env
  O(15)  Test_Type
  P(16)  Scenario_Type
  Q(17)  Remarks/Additional information  -- bullet format, no test-basis (Req 8)
  R(18)  Module               -- alpha-only (Req 7)

  NOTE: Column positions G/J/K/M etc. shift right if there are more input/output signals.
  The template example has 3 input signals and 2 output signals, giving:
    G(7)=Inputs header, H(8)=sig1, I(9)=sig2, [J(10)=sig3 if 3 inputs]
  Since signals are dynamic, we compute offsets at runtime.
"""

import io
import re
from datetime import datetime
from typing import List, Dict, Tuple

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from docx import Document as DocxDocument
from docx.shared import Pt, RGBColor, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH

from models import TestCase
from config import ENGINE


# ─── STYLING — Uniform colour scheme (Requirement 6) ─────────────────────────
# All header cells use the same blue fill; no per-column different colours.
HEADER_FILL   = PatternFill("solid", fgColor="4472C4")   # uniform blue
HEADER_FONT   = Font(bold=True, color="FFFFFF", size=10, name="Calibri")
HEADER_ALIGN  = Alignment(horizontal="center", vertical="center", wrap_text=True)

SUBHDR_FILL   = PatternFill("solid", fgColor="4472C4")   # same blue for sub-headers (Req 6)
SUBHDR_FONT   = Font(bold=True, color="FFFFFF", size=9,  name="Calibri")
SUBHDR_ALIGN  = Alignment(horizontal="center", vertical="center", wrap_text=True)

BODY_FONT     = Font(size=9, name="Calibri")
BODY_ALIGN    = Alignment(vertical="top", wrap_text=True)
CENTER_ALIGN  = Alignment(horizontal="center", vertical="top", wrap_text=True)

THIN_SIDE     = Side(style="thin", color="CCCCCC")
THIN_BORDER   = Border(left=THIN_SIDE, right=THIN_SIDE, top=THIN_SIDE, bottom=THIN_SIDE)

ALT_FILL      = PatternFill("solid", fgColor="EEF2F9")   # alternating row shading


# ─── SIGNAL EXTRACTION ────────────────────────────────────────────────────────

# Accept both "Signal: Value" (rule-based) and "Signal = Value" (Claude AI) formats
_KV_COLON = re.compile(r'^(.+?):\s*(.+)$')
_KV_EQUAL  = re.compile(r'^(.+?)\s*=\s*(.+)$')

# TC methodologies that always produce proper "SignalName: Value" inputs
_SIGNAL_METHODOLOGIES = {
    "mc/dc testing",
    "condition coverage testing",
    "decision table testing",
}

# Generic phrases that disqualify an input entry as a named signal
_GENERIC_INPUT_PHRASES = {
    "valid data", "invalid data", "boundary value", "valid inputs",
    "sql injection", "xss payload", "malformed", "oversized input",
    "concurrent request", "session timeout", "state transition",
    "out-of-range", "sub-requirements scope", "combined inputs",
    "conforming to srs", "test environment", "all prerequisite",
    "exercising the full", "satisfying all sub",
}

# Phrases that disqualify an output signal name
_OUTPUT_SKIP_PHRASES = {
    "system successfully", "response is", "data is", "result is",
    "all sub", "no data", "logic module", "specification",
    "test case", "is correct", "the logic", "and sets",
    "for scenario", "scenario sc", "this single",
    "the output", "all conditions", "sub-requirements",
    "no gaps", "the system", "collectively", "correctly",
    "evaluates to", "independence criterion", "causes the",
    # Generic placeholders that Claude AI or the fallback path may produce —
    # these are never real signal names and must not appear as column sub-headers.
    "output signal", "output value", "output state", "expected output",
    "signal output", "signal value", "signal name",
}
_OUTPUT_STARTER_SKIP = {
    "the", "a", "an", "this", "all", "no", "for",
    "system", "response", "data", "result", "and",
    "output",   # prevents "output signal", "output value" etc. from becoming a signal name
}


def _parse_signal_value(entry: str) -> Tuple[str, str]:
    """Parses 'Name: Value' or 'Name = Value' into (name, value)."""
    s = entry.strip()
    # Prefer colon separator (standard format), fall back to equals
    m = _KV_COLON.match(s) or _KV_EQUAL.match(s)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return s, ""


def _is_valid_input_signal(entry: str, is_signal_tc: bool) -> bool:
    """
    Returns True if entry is a proper named signal input.
    Accepts both:
      "SignalName: Value"   (rule-based engine format)
      "SignalName = Value"  (Claude AI generated format)
    """
    if ':' not in entry and '=' not in entry:
        return False
    name, value = _parse_signal_value(entry)
    if not name or not value:
        return False
    # Name must be 1-8 words
    if not (1 <= len(name.split()) <= 8):
        return False
    # Name must not be a generic phrase
    name_lower = name.lower()
    if any(phrase in name_lower for phrase in _GENERIC_INPUT_PHRASES):
        return False
    if is_signal_tc:
        # For signal TCs: accept single or multi-word values (True/False/Active/Inactive/Running)
        # Reject only obvious generic descriptions
        return True
    else:
        # For standard TCs: value must be 1 word (pure enum/boolean)
        value_words = value.split()
        if len(value_words) != 1:
            return False
        generic_vals = {"valid","invalid","none","null","undefined","minimum",
                        "maximum","boundary","normal","standard","initialised",
                        "initialized","configured","enabled","disabled",
                        "authorised","authorized","authenticated"}
        if value_words[0].lower() in generic_vals:
            return False
        return True


def _parse_output_clause(clause: str) -> List[Tuple[str, str]]:
    """
    Parses a clause like "Signal1 = Value1; Signal2 = Value2"
    into [("Signal1", "Value1"), ("Signal2", "Value2")].
    Skips entries where the name is a generic phrase.
    """
    results = []
    # Split on semicolons to handle multiple signals
    parts_list = clause.split(";")
    for part in parts_list:
        part = part.strip()
        if "=" not in part:
            continue
        parts = part.split("=", 1)
        if len(parts) != 2:
            continue
        raw_name  = parts[0].strip()
        value_raw = parts[1].strip()
        name  = re.sub(r'^(?:the|a|an|this)\s+', '', raw_name, flags=re.IGNORECASE).strip()
        value = value_raw.split()[0].rstrip(".,;:") if value_raw else ""
        if not name or len(name) < 2 or not value:
            continue
        words = name.split()
        if not (1 <= len(words) <= 8):
            continue
        if words[0].lower() in _OUTPUT_STARTER_SKIP:
            continue
        if any(p in name.lower() for p in _OUTPUT_SKIP_PHRASES):
            continue
        results.append((name, value))
    return results


def _extract_all_output_signals_with_values(
    expected_outcome: str,
    exclude_names: set = None,
) -> List[Tuple[str, str]]:
    """
    Returns list of (signal_name, value) pairs from expected_outcome.

    Handles ALL formats:
      "SignalName = Value. ..."                       <- rule-based standard
      "For scenario SC_N: Signal = V; Signal2 = V2." <- decision table
      " = Value. AND-decision evaluates..."           <- empty output_name
      "...sets SignalName to Value..."                <- Claude AI prose
      "...SignalName is Value..."                     <- Claude AI prose

    If exclude_names is provided (set of input signal names),
    those names are excluded from output detection.
    """
    if not expected_outcome:
        return []

    excl = {n.lower() for n in (exclude_names or set())}
    results: List[Tuple[str, str]] = []
    seen: set = set()

    def _add(name: str, value: str) -> bool:
        """Validates and adds (name, value) if not already seen."""
        name  = re.sub(r'^(?:the|a|an|this)\s+', '', name, flags=re.IGNORECASE).strip()
        if not name or len(name) < 2:
            return False
        words = name.split()
        if not (1 <= len(words) <= 8):
            return False
        if words[0].lower() in _OUTPUT_STARTER_SKIP:
            return False
        if any(p in name.lower() for p in _OUTPUT_SKIP_PHRASES):
            return False
        if name.lower() in excl:
            return False
        if name.lower() in seen:
            return False
        seen.add(name.lower())
        results.append((name, value))
        return True

    # ── Strategy 1: first clause "Signal = Value" (standard / decision table) ─
    if "=" in expected_outcome:
        first_clause = expected_outcome.split(".")[0].strip()
        if ":" in first_clause:
            after = first_clause.rsplit(":", 1)[1].strip()
            if "=" in after:
                first_clause = after
        if "=" in first_clause:
            for part in first_clause.split(";"):
                part = part.strip()
                if "=" not in part:
                    continue
                pts = part.split("=", 1)
                raw_name  = pts[0].strip()
                value_raw = pts[1].strip() if len(pts) > 1 else ""
                name  = re.sub(r'^(?:the|a|an|this)\s+', '', raw_name, flags=re.IGNORECASE).strip()
                value = value_raw.split()[0].rstrip(".,;:") if value_raw else ""
                if name and value:
                    _add(name, value)

    # ── Strategy 2: full scan for "Signal = BoolValue" (handles prose) ────────
    # Used when strategy 1 finds nothing or for additional signals
    _BOOL_VALS = r'(True|False|TRUE|FALSE|Enable|Disable|Active|Inactive|Enabled|Disabled|1|0)'
    for m in re.finditer(
        r'([A-Z][\w\s]{2,60}?)\s*=\s*' + _BOOL_VALS + r'\b',
        expected_outcome
    ):
        cand = m.group(1).strip()
        val  = m.group(2).strip()
        _add(cand, val)

    # ── Strategy 3: "sets SignalName to Value" ────────────────────────────────
    # e.g. "...sets Altitude Alert Condition Enabled to True..."
    for m in re.finditer(
        r'sets?\s+([A-Z][\w\s]{2,50}?)\s+to\s+[\'"]?' + _BOOL_VALS + r'[\'"]?\b',
        expected_outcome, re.IGNORECASE
    ):
        _add(m.group(1).strip(), m.group(2).strip())

    # ── Strategy 4: "SignalName [output] is set to 'Value'" ──────────────────
    # Catches Claude AI pattern: "Altitude Alert Condition Enabled output is set to 'True'"
    # or: "Is Enabled of Auto Start State is set to 'Enable'"
    for m in re.finditer(
        r'([A-Z][\w\s]{2,60}?)\s+(?:output\s+)?is\s+set\s+to\s+[\'"]?' + _BOOL_VALS + r'[\'"]?',
        expected_outcome, re.IGNORECASE
    ):
        cand = re.sub(r'\s+output\s*$', '', m.group(1).strip(), flags=re.IGNORECASE).strip()
        _add(cand, m.group(2).strip())

    # ── Strategy 5: "SignalName is/equals/becomes Value" ──────────────────────
    # e.g. "Altitude Alert Condition Enabled is True"
    for m in re.finditer(
        r'([A-Z][\w\s]{2,50}?)\s+(?:is|equals?|becomes?)\s+[\'"]?' + _BOOL_VALS + r'[\'"]?\b',
        expected_outcome
    ):
        _add(m.group(1).strip(), m.group(2).strip())

    return results


def _extract_all_output_signals(
    expected_outcome: str,
    exclude_names: set = None,
) -> List[str]:
    """Returns list of output signal names (without values)."""
    return [
        name
        for name, _ in _extract_all_output_signals_with_values(
            expected_outcome, exclude_names=exclude_names
        )
    ]


def _extract_output_signal(expected_outcome: str) -> Tuple[str, str]:
    """
    Extracts (signal_name, value) from expected_outcome.

    Handles all formats:
      "SignalName = Value. ..."
      "For scenario SC_N: SignalName = Value. ..."
      " = Value. AND-decision..."  -- empty output_name fallback: scans full text
    """
    if not expected_outcome or '=' not in expected_outcome:
        return "", ""

    first_clause = expected_outcome.split('.')[0].strip()

    # Strip "For scenario SC_N:" prefix
    if ':' in first_clause:
        after = first_clause.rsplit(':', 1)[1].strip()
        if '=' in after:
            first_clause = after

    if '=' not in first_clause:
        return "", ""

    parts = first_clause.split('=', 1)
    if len(parts) != 2:
        return "", ""

    raw_name  = parts[0].strip()
    value_raw = parts[1].strip()
    value     = value_raw.split()[0].rstrip('.,;:') if value_raw else ""
    if not value:
        return "", ""

    name = re.sub(r'^(?:the|a|an|this)\s+', '', raw_name, flags=re.IGNORECASE).strip()

    # Empty signal name (output_name was empty in generator)
    # Scan full expected_outcome for "SignalName = BoolValue" pattern
    if not name or len(name) < 2:
        for m in re.finditer(
            r'([A-Z][\w\s]{2,50}?)\s*=\s*(True|False|TRUE|FALSE|Active|Inactive|1|0)\b',
            expected_outcome
        ):
            candidate  = m.group(1).strip()
            cand_val   = m.group(2).strip()
            cand_words = candidate.split()
            if not (1 <= len(cand_words) <= 8):
                continue
            if cand_words[0].lower() in _OUTPUT_STARTER_SKIP:
                continue
            if any(p in candidate.lower() for p in _OUTPUT_SKIP_PHRASES):
                continue
            return candidate, cand_val
        return "", ""

    # Validate signal name
    words = name.split()
    if not (1 <= len(words) <= 8):
        return "", ""
    if words[0].lower() in _OUTPUT_STARTER_SKIP:
        return "", ""
    if any(phrase in name.lower() for phrase in _OUTPUT_SKIP_PHRASES):
        return "", ""

    return name, value


def extract_signal_columns(test_cases: List[TestCase]) -> Tuple[List[str], List[str]]:
    """
    Returns (input_signal_names, output_signal_names) for the given test cases.

    Input signals:
      - For condition coverage / decision table / MC/DC TCs: all "Name: Value"
        inputs are treated as signals (they are always proper signal pairs).
      - For standard TCs: only single-word-value inputs qualify.

    Output signals:
      - Extracted from the first clause of expected_outcome using "SignalName = Value"
        format. Handles "For scenario SC_N: SignalName = Value" prefix correctly.
    """
    in_sigs:  List[str] = []
    out_sigs: List[str] = []
    seen_in:  set = set()
    seen_out: set = set()

    for tc in test_cases:
        is_signal_tc = tc.design_methodology.lower() in _SIGNAL_METHODOLOGIES

        # ── Input signals ──────────────────────────────────────────────────────
        for entry in tc.inputs:
            if not _is_valid_input_signal(entry, is_signal_tc):
                continue
            name, _ = _parse_signal_value(entry)
            if name and name not in seen_in:
                seen_in.add(name)
                in_sigs.append(name)

        # ── Output signals ─────────────────────────────────────────────────────
        # Detect output signals from expected_outcome.
        # Pass seen_in so input signal names are excluded from output detection.
        # Handles all formats: "Signal = Value", prose "sets X to Y", "X is Y"
        for sig_name, _ in _extract_all_output_signals_with_values(
            tc.expected_outcome, exclude_names=seen_in
        ):
            if sig_name not in seen_out:
                seen_out.add(sig_name)
                out_sigs.append(sig_name)

    return in_sigs, out_sigs


def _get_signal_value(tc: TestCase, signal_name: str, kind: str) -> str:
    """Returns the value for a specific signal from a test case."""
    if kind == "input":
        for entry in tc.inputs:
            name, value = _parse_signal_value(entry)
            if name.lower() == signal_name.lower():
                return value
        return ""
    # Output: search in expected_outcome, excluding input signal names
    # Build a rough set of input-like names from tc.inputs to exclude
    input_names = set()
    for entry in tc.inputs:
        n, _ = _parse_signal_value(entry)
        if n:
            input_names.add(n)
    for sname, sval in _extract_all_output_signals_with_values(
        tc.expected_outcome, exclude_names=input_names
    ):
        if sname.lower() == signal_name.lower():
            return sval
    return ""


# ─── FIELD HELPERS ────────────────────────────────────────────────────────────

def _list_to_str(value) -> str:
    if isinstance(value, list):
        return "\n".join(str(v) for v in value if v)
    return str(value) if value else ""


def _cell_value(tc: TestCase, field: str) -> str:
    return _list_to_str(getattr(tc, field, ""))


def _module_alpha_only(module: str) -> str:
    """Requirement 7: keep only alphabetical characters and spaces."""
    cleaned = re.sub(r'[^A-Za-z\s]', '', module).strip()
    return re.sub(r'\s+', ' ', cleaned) or "General"


def _sc_label(sc_no: int) -> str:
    """Format scenario number as SC_001, SC_002, etc. to match template."""
    return f"SC_{sc_no:03d}"


# ─── REQUIREMENT 5: Column F content ─────────────────────────────────────────
# Col F = Test Precondition, but per Req 5 it must consolidate:
#   • Test Objective (from col D/E)
#   • Test Steps that are related to the identified input parameter names (from H, I... cols)

def _col_f_precondition(tc: TestCase, input_signals: List[str]) -> str:
    """
    Column F — Test Precondition.
    Contains ONLY the actual preconditions for the test case.
    Does NOT include test objective, test steps, or pre-set input values
    (those belong in their own dedicated columns).
    """
    if not tc.preconditions:
        return ""
    return _list_to_str(tc.preconditions)


# ─── REQUIREMENT 8: Remarks bullet formatting ─────────────────────────────────

def _remarks_bullets(tc: TestCase) -> str:
    """
    Requirement 8:
    - Remove test-basis-related info
    - Include type of testing per scenario
    - Describe what is tested in each SC (e.g. INPUT_1 maximum value is tested)
    - Bullet-point format
    """
    bullets = []

    # Type of testing for this scenario
    bullets.append(f"• Testing Type: {tc.testing_type.capitalize()} | Scenario Type: {tc.scenario_type.capitalize()}")

    # What is being tested (Req 8 — describe each SC)
    sc_what = {
        "normal":     "All input values set to normal/valid values; correct system output is verified.",
        "boundary":   "Input boundary values tested: minimum, maximum, min-1, max+1 for each parameter.",
        "edge":       "Edge case conditions tested (state transitions, simultaneous changes, unusual-but-valid states).",
        "robustness": "Invalid/out-of-range input values tested; system must respond safely without crash.",
    }
    bullets.append(f"• What is tested: {sc_what.get(tc.scenario_type, 'Functional system behaviour verified.')}")

    # Per-input description (e.g. "INPUT_1 maximum value is tested")
    for entry in tc.inputs:
        name, value = _parse_signal_value(entry)
        if name and value and name.lower() not in ("test environment", "all prerequisite", "sub-requirements"):
            if tc.scenario_type == "boundary":
                if "max" in value.lower() or "maximum" in value.lower():
                    bullets.append(f"• {name}: maximum value is tested")
                elif "min" in value.lower() or "minimum" in value.lower():
                    bullets.append(f"• {name}: minimum value is tested")
                elif "-1" in value or "below" in value.lower():
                    bullets.append(f"• {name}: below-minimum value is tested (invalid range)")
                elif "+1" in value or "above" in value.lower():
                    bullets.append(f"• {name}: above-maximum value is tested (invalid range)")
                else:
                    bullets.append(f"• {name}: boundary value '{value}' is tested")
            elif tc.scenario_type == "edge":
                bullets.append(f"• {name}: edge-case value '{value}' is tested (state-transition condition)")
            elif tc.scenario_type == "robustness":
                bullets.append(f"• {name}: invalid/out-of-range value '{value}' is tested")

    # Input source note (Req 4)
    inputs_raw = " ".join(tc.inputs).lower()
    if any(kw in inputs_raw for kw in ["icd", "derived", "interface"]):
        bullets.append("• Input source: Values derived from ICD document (not explicitly defined in SRS).")
    else:
        bullets.append("• Input source: Input values explicitly defined in SRS specification.")

    # Sub-requirements / cross-refs from raw remarks (strip test-basis lines)
    if tc.remarks:
        raw_parts = re.split(r'\s*[\|\n•]+\s*', tc.remarks)
        for part in raw_parts:
            part = part.strip()
            if not part:
                continue
            # Remove test-basis lines (Req 8)
            if re.search(
                r'test\s+basis|input\s+values\s+derived\s+from\s+srs|srs\s+requirement\s+\w',
                part, re.IGNORECASE
            ):
                continue
            # Include enum definitions, sub-req refs, notes
            if re.search(r'enum|sub.req|note|reference|derived from icd|document context', part, re.IGNORECASE):
                bullets.append(f"• {part}")

    return "\n".join(bullets)


# ─── REQUIREMENT 10: Depends On ───────────────────────────────────────────────

def _depends_on(raw_dep: str, tc_id: str, sc_no: int) -> str:
    """
    Depands On column.
    Format: TC_UT_001_SC-001  (hyphen between SC and number)

    The generator writes:
      - "None"            for SC_001 (baseline)
      - "TC_UT_001_SC-001" for SC_002+ (always references baseline with hyphen)

    This function passes the value through unchanged if already formatted,
    or applies a fallback for legacy/MCP data.
    """
    if not raw_dep or raw_dep.strip().lower() == "none":
        return "None"
    raw = raw_dep.strip()
    # Already formatted (TC_ID_SC-001 hyphen format or TC_ID_SC_001 underscore)
    if "_SC-" in raw or "_SC_" in raw.upper():
        return raw
    # Fallback: bare TC_ID — append SC-001 (baseline reference, hyphen format)
    return f"{raw}_SC-001"


# ─── HEADER WRITER ────────────────────────────────────────────────────────────

def _write_headers(ws, input_signals: List[str], output_signals: List[str]) -> Dict[str, int]:
    """
    Writes rows 1 and 2 exactly matching One_TC_Updated.xlsx template.
    Returns a dict of column-name -> column-index for use when writing data.

    Template exact layout:
      Col 1: Requirement_ID  (rows 1-2 merged)
      Col 2: TC_ID           (rows 1-2 merged)
      Col 3: Scenario No     (rows 1-2 merged)
      Col 4: Test Objective  (rows 1-2 merged)
      Col 5: Test Details Description  (rows 1-2 merged)
      Col 6: Test Precondition         (rows 1-2 merged)
      Col 7: Inputs          (row 1 merged across input signal sub-cols)
        Col 7+0: signal_1 sub-header (row 2)
        Col 7+1: signal_2 sub-header (row 2)
        ...
      Col 7+n_inputs: Test Steps       (rows 1-2 merged)
      Col 7+n_inputs+1: Expected Outputs (row 1 merged across output sub-cols)
        output signal sub-headers (row 2)  ← same treatment as input sub-headers
      Col 7+n_inputs+1+n_outputs: Depands On   (rows 1-2 merged)  [sic]
      Col ...: Test_Env       (rows 1-2 merged)
      Col ...: Test_Type      (rows 1-2 merged)
      Col ...: Scenario_Type  (rows 1-2 merged)
      Col ...: Remarks/Additional information  (rows 1-2 merged)
      Col ...: Module          (rows 1-2 merged)
    """
    n_in  = len(input_signals)
    n_out = len(output_signals)

    # Fixed prefix columns A-F
    prefix = [
        ("Requirement_ID",          21),
        ("TC_ID",                    9),
        ("Scenario No",             12),
        ("Test Objective",          20),
        ("Test Details Description",22),
        ("Test Precondition",       45),
    ]

    col = 1
    col_map: Dict[str, int] = {}

    # Write prefix headers (each spans rows 1-2)
    for hdr, width in prefix:
        c = ws.cell(row=1, column=col, value=hdr)
        c.font = HEADER_FONT; c.fill = HEADER_FILL
        c.alignment = HEADER_ALIGN; c.border = THIN_BORDER
        ws.column_dimensions[get_column_letter(col)].width = width
        ws.merge_cells(start_row=1, start_column=col, end_row=2, end_column=col)
        col_map[hdr] = col
        col += 1

    # "Inputs" group header at col G
    inputs_start = col
    col_map["Inputs_start"] = inputs_start
    c = ws.cell(row=1, column=col, value="Inputs")
    c.font = HEADER_FONT; c.fill = HEADER_FILL
    c.alignment = HEADER_ALIGN; c.border = THIN_BORDER
    if n_in > 1:
        ws.merge_cells(start_row=1, start_column=col, end_row=1, end_column=col + n_in - 1)
    elif n_in == 0:
        ws.merge_cells(start_row=1, start_column=col, end_row=2, end_column=col)

    # Input signal sub-headers in row 2
    for i, sig in enumerate(input_signals):
        c2 = ws.cell(row=2, column=col + i, value=sig)
        c2.font = SUBHDR_FONT; c2.fill = SUBHDR_FILL   # same blue (Req 6)
        c2.alignment = SUBHDR_ALIGN; c2.border = THIN_BORDER
        ws.column_dimensions[get_column_letter(col + i)].width = max(18, len(sig) + 4)
        col_map[f"input_sig_{i}"] = col + i
    col += max(n_in, 1)  # advance at least 1 column

    # "Test Steps" standalone column
    col_map["Test Steps"] = col
    c = ws.cell(row=1, column=col, value="Test Steps")
    c.font = HEADER_FONT; c.fill = HEADER_FILL
    c.alignment = HEADER_ALIGN; c.border = THIN_BORDER
    ws.column_dimensions[get_column_letter(col)].width = 30
    ws.merge_cells(start_row=1, start_column=col, end_row=2, end_column=col)
    col += 1

    # "Expected Outputs" group header
    # Row 1: "Expected Outputs" merged across all output sub-columns (like "Inputs" group).
    # Row 2: each output signal name as a sub-header (same blue style as input sub-headers).
    # Data rows: each output signal gets its own sub-column containing ONLY the plain value.
    outputs_start = col
    col_map["Outputs_start"] = outputs_start
    c = ws.cell(row=1, column=col, value="Expected Outputs")
    c.font = HEADER_FONT; c.fill = HEADER_FILL
    c.alignment = HEADER_ALIGN; c.border = THIN_BORDER
    if n_out > 1:
        ws.merge_cells(start_row=1, start_column=col, end_row=1, end_column=col + n_out - 1)
    elif n_out == 0:
        # No output signals — merge row 1 and row 2 into a single cell
        ws.merge_cells(start_row=1, start_column=col, end_row=2, end_column=col)

    # Write output signal sub-headers in row 2 (identical treatment to input signals)
    for i, sig in enumerate(output_signals):
        c2 = ws.cell(row=2, column=col + i, value=sig)
        c2.font = SUBHDR_FONT; c2.fill = SUBHDR_FILL
        c2.alignment = SUBHDR_ALIGN; c2.border = THIN_BORDER
        ws.column_dimensions[get_column_letter(col + i)].width = max(22, len(sig) + 4)
        col_map[f"output_sig_{i}"] = col + i
    col += max(n_out, 1)

    # Suffix columns — all same blue header (Req 6)
    suffix = [
        ("Depands On",                      12),   # sic — typo preserved from template
        ("Test_Env",                        12),
        ("Test_Type",                       16),
        ("Scenario_Type",                   14),
        ("Remarks/Additional information",  32),
        ("Module",                           9),
    ]
    for hdr, width in suffix:
        c = ws.cell(row=1, column=col, value=hdr)
        c.font = HEADER_FONT; c.fill = HEADER_FILL
        c.alignment = HEADER_ALIGN; c.border = THIN_BORDER
        ws.column_dimensions[get_column_letter(col)].width = width
        ws.merge_cells(start_row=1, start_column=col, end_row=2, end_column=col)
        col_map[hdr] = col
        col += 1

    ws.row_dimensions[1].height = 28
    ws.row_dimensions[2].height = 22
    ws.freeze_panes = "A3"
    return col_map


# ─── OUTPUT VALUE EXTRACTOR ───────────────────────────────────────────────────

def _extract_output_value_only(expected_outcome: str) -> str:
    """
    Extracts ONLY the plain value from an expected_outcome string.

    Handles these formats and returns just the value token:
      "SignalName = True. ..."           -> "True"
      "SignalName = False. ..."          -> "False"
      "For scenario SC_001: X = True."  -> "True"
      "System successfully executes..."  -> first sentence (no signal prefix found)

    The goal is to never write "SignalName = Value" into the output cell —
    only "Value" (or a short descriptive first-sentence if no signal is present).
    """
    if not expected_outcome:
        return ""

    first_clause = expected_outcome.split('.')[0].strip()

    # Strip "For scenario SC_N:" prefix
    if ':' in first_clause:
        after = first_clause.rsplit(':', 1)[1].strip()
        if '=' in after:
            first_clause = after

    if '=' in first_clause:
        parts = first_clause.split('=', 1)
        if len(parts) == 2:
            raw_value = parts[1].strip()
            value = raw_value.split()[0].rstrip('.,;:') if raw_value else ""
            # Accept only unambiguous boolean / enum tokens as the extracted value
            _KNOWN_VALUES = {
                'true', 'false', 'enabled', 'disabled',
                'active', 'inactive', '1', '0',
                'pass', 'fail', 'yes', 'no', 'set', 'reset',
                'on', 'off', 'high', 'low', 'open', 'closed',
                'valid', 'invalid',
            }
            if value and value.lower() in _KNOWN_VALUES:
                return value

    # No clean signal=value prefix found — return the first sentence as-is
    # (covers standard TCs whose outcome starts with "System successfully…")
    return first_clause if first_clause else ""


# ─── STANDALONE ROW WRITER ────────────────────────────────────────────────────

def _write_tc_row(ws, row_idx: int, tc: TestCase,
                  col_map: dict, in_sigs: List[str], out_sigs: List[str]) -> None:
    """
    Writes one TC row into worksheet ws.
    Standalone function — no closure issues.
    Each input signal goes into its OWN sub-column.
    Each output signal goes into its OWN sub-column.
    Falls back to combined text when no signals detected.
    """
    is_alt = (row_idx % 2 == 0)
    tc_id  = tc.test_case_id
    sc_lbl = tc.scenario_id
    sc_no  = int(sc_lbl.replace("SC_", "")) if sc_lbl.startswith("SC_") else row_idx - 2

    def _p(col: int, value, center: bool = False):
        cell = ws.cell(row=row_idx, column=col, value=value)
        cell.font      = BODY_FONT
        cell.alignment = CENTER_ALIGN if center else BODY_ALIGN
        cell.border    = THIN_BORDER
        if is_alt:
            cell.fill  = ALT_FILL

    # ── Fixed columns ──────────────────────────────────────────────────────────
    _p(col_map["Requirement_ID"],          tc.traceability_req_id)
    _p(col_map["TC_ID"],                   tc_id)
    _p(col_map["Scenario No"],             sc_lbl)
    _p(col_map["Test Objective"],          tc.objective)
    _p(col_map["Test Details Description"],_list_to_str(tc.preconditions))
    _p(col_map["Test Precondition"],       _col_f_precondition(tc, in_sigs))

    # ── Input sub-columns ──────────────────────────────────────────────────────
    # Each signal gets its OWN column: Inputs_start+0, Inputs_start+1, …
    # For TCs that have named signal inputs (MCDC / decision-table) each signal
    # value is written into its dedicated sub-column.
    # For standard TCs whose inputs are generic template strings (no matching
    # signal names), we fall back to writing the combined inputs text in the
    # first sub-column so the row is never left completely blank.
    if in_sigs:
        # Collect per-signal values for this TC
        sig_values = [_get_signal_value(tc, sig, "input") for sig in in_sigs]
        if any(sig_values):
            # At least one signal matched → write per-signal
            for idx_i, val in enumerate(sig_values):
                _p(col_map["Inputs_start"] + idx_i, val, center=True)
        else:
            # No signal matched (standard / generic TC) → write combined text
            # in the first sub-column; leave the others empty (they belong to
            # signal TCs on the same sheet).
            _p(col_map["Inputs_start"], _list_to_str(tc.inputs))
    else:
        # No named signals at all → write combined text to the single Inputs cell
        _p(col_map["Inputs_start"], _list_to_str(tc.inputs))

    # ── Test Steps ─────────────────────────────────────────────────────────────
    _p(col_map["Test Steps"], _list_to_str(tc.test_steps))

    # ── Output sub-columns ─────────────────────────────────────────────────────
    # Each output signal gets its OWN column: Outputs_start+0, +1, …
    # The cell must contain ONLY the plain value (True / False / Active / …)
    # with no signal-name label prefix.
    if out_sigs:
        for idx_o, sig in enumerate(out_sigs):
            val = _get_signal_value(tc, sig, "output")
            _p(col_map["Outputs_start"] + idx_o, val, center=True)
    else:
        # No named output signals — extract only the value from expected_outcome.
        # If the outcome begins with "SignalName = Value." we want just "Value".
        # Otherwise fall back to the first sentence.
        _p(col_map["Outputs_start"], _extract_output_value_only(tc.expected_outcome), center=True)

    # ── Suffix columns ─────────────────────────────────────────────────────────
    _p(col_map["Depands On"],
       _depends_on(tc.dependent_test_cases, tc_id, sc_no))
    _p(col_map["Test_Env"],      tc.test_environment)
    _p(col_map["Test_Type"],     tc.testing_type)
    _p(col_map["Scenario_Type"], tc.scenario_type)
    _p(col_map["Remarks/Additional information"], _remarks_bullets(tc))
    _p(col_map["Module"],        _module_alpha_only(tc.module))


# ─── SAFE SHEET NAME ───────────────────────────────────────────────────────────

def _safe_sheet_name(req_id: str, used: set) -> str:
    """Converts req_id to valid Excel sheet name; resolves collisions."""
    clean = re.sub(r'[\\/*?:\[\]]', '_', req_id)
    clean = re.sub(r'[,\s]+', '_', clean)
    clean = re.sub(r'_+', '_', clean).strip('_')
    base  = clean[:31]
    name  = base
    n     = 1
    while name in used:
        suffix = f"_{n:02d}"
        name   = base[:31 - len(suffix)] + suffix
        n     += 1
    return name


# ─── EXCEL EXPORT ─────────────────────────────────────────────────────────────

def generate_excel(test_cases: List[TestCase], removed_count: int) -> bytes:
    """
    Generate Excel matching One_TC_Updated.xlsx template exactly.
    All requirements applied:
      Req 3:  TC_ID same for all scenarios of one req; SC resets per req
      Req 4:  Input source (SRS/ICD) recorded in Remarks
      Req 5:  Col F = Test Objective + input-related Test Steps
      Req 6:  Uniform blue header colour throughout
      Req 7:  Module = alpha-only
      Req 8:  Remarks = bullet format, no test-basis, SC description
      Req 9:  Precondition includes pre-set values + output-influence note
      Req 10: Depands On = TC_ID + SC_NNN
    """
    wb = openpyxl.Workbook()
    # Remove the default empty sheet created by openpyxl — we do NOT want a
    # combined "test_cases" sheet; each requirement gets its own sheet instead.
    default_ws = wb.active
    wb.remove(default_ws)

    # ── Summary sheet ─────────────────────────────────────────────────────────
    ws2 = wb.create_sheet(title="Summary")
    ws2.column_dimensions["A"].width = 35
    ws2.column_dimensions["B"].width = 25

    sum_hdr_font = Font(bold=True, color="FFFFFF", size=11, name="Calibri")
    sum_hdr_fill = PatternFill("solid", fgColor="2F4F8F")
    lbl_font     = Font(bold=True, size=10, name="Calibri")
    val_font     = Font(size=10, name="Calibri")

    def _sh_title(r, text):
        c = ws2.cell(row=r, column=1, value=text)
        c.font = sum_hdr_font; c.fill = sum_hdr_fill
        ws2.merge_cells(start_row=r, start_column=1, end_row=r, end_column=2)
        c.alignment = Alignment(horizontal="center")

    def _sh_row(r, label, value):
        ws2.cell(row=r, column=1, value=label).font = lbl_font
        ws2.cell(row=r, column=2, value=value).font = val_font

    from collections import Counter
    r = 1
    _sh_title(r, "Test Case Generation Summary"); r += 1
    _sh_row(r, "Total Test Cases", len(test_cases)); r += 1
    _sh_row(r, "Duplicates Removed", removed_count); r += 1
    _sh_row(r, "Generated On", datetime.now().strftime("%Y-%m-%d %H:%M:%S")); r += 2

    _sh_title(r, "By Module"); r += 1
    for mod, cnt in sorted(Counter(_module_alpha_only(tc.module) for tc in test_cases).items()):
        _sh_row(r, mod, cnt); r += 1
    r += 1

    _sh_title(r, "By Scenario Type"); r += 1
    for st, cnt in sorted(Counter(tc.scenario_type for tc in test_cases).items()):
        _sh_row(r, st.capitalize(), cnt); r += 1
    r += 1

    _sh_title(r, "By Testing Type"); r += 1
    for tt, cnt in sorted(Counter(tc.testing_type for tc in test_cases).items()):
        _sh_row(r, tt.capitalize(), cnt); r += 1

    # ── Per-requirement sheets ────────────────────────────────────────────────
    # Every unique traceability_req_id gets its own sheet with ONLY its own
    # signal columns. Requirements differing only in ID number get separate sheets.
    from collections import OrderedDict
    req_groups: OrderedDict = OrderedDict()
    for tc in test_cases:
        rid = tc.traceability_req_id
        if rid not in req_groups:
            req_groups[rid] = []
        req_groups[rid].append(tc)

    used_names: set = {ws.title for ws in wb.worksheets}

    for req_id, req_tcs in req_groups.items():
        sname    = _safe_sheet_name(req_id, used_names)
        used_names.add(sname)
        ws_r     = wb.create_sheet(title=sname)

        # Each requirement sheet uses ONLY its own signal columns
        r_in, r_out = extract_signal_columns(req_tcs)
        r_cmap      = _write_headers(ws_r, r_in, r_out)

        for row_idx, tc in enumerate(req_tcs, start=3):
            _write_tc_row(ws_r, row_idx, tc, r_cmap, r_in, r_out)

    # Summary sheet always last
    wb.move_sheet("Summary", offset=len(wb.worksheets) - 1)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ─── WORD EXPORT ──────────────────────────────────────────────────────────────

def generate_docx(test_cases: List[TestCase], removed_count: int) -> bytes:
    doc = DocxDocument()
    for section in doc.sections:
        section.top_margin = section.bottom_margin = Inches(0.8)
        section.left_margin = section.right_margin = Inches(0.9)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run("Test Case Report")
    run.font.size = Pt(20); run.font.bold = True
    run.font.color.rgb = RGBColor(0x44, 0x72, 0xC4)

    meta = doc.add_paragraph()
    meta.alignment = WD_ALIGN_PARAGRAPH.CENTER
    meta.add_run(
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}  |  "
        f"Total: {len(test_cases)} test cases  |  Duplicates removed: {removed_count}"
    ).font.size = Pt(9)
    doc.add_paragraph()

    from collections import defaultdict
    by_module = defaultdict(list)
    for tc in test_cases:
        by_module[_module_alpha_only(tc.module)].append(tc)

    input_signals, output_signals = extract_signal_columns(test_cases)

    for module in sorted(by_module.keys()):
        h = doc.add_paragraph(f"Module: {module}")
        h.style = "Heading 1"

        for tc in by_module[module]:
            req_id = tc.traceability_req_id
            tc_id  = tc.test_case_id
            sc_lbl = tc.scenario_id
            sc_no  = int(sc_lbl.replace("SC_", "")) if sc_lbl.startswith("SC_") else 1

            sub = doc.add_paragraph(f"{tc_id} | {sc_lbl} | {tc.scenario_type.capitalize()}")
            sub.style = "Heading 2"

            rows = [
                ("Requirement_ID",          req_id),
                ("TC_ID",                   tc_id),
                ("Scenario No",             sc_lbl),
                ("Test Objective",          tc.objective),
                ("Test Details Description",_list_to_str(tc.preconditions)),
                ("Test Precondition",       _col_f_precondition(tc, input_signals)),
                ("Inputs",                  _list_to_str(tc.inputs)),
                ("Test Steps",              _list_to_str(tc.test_steps)),
                ("Expected Outputs",        tc.expected_outcome),
                ("Depands On",              _depends_on(tc.dependent_test_cases, tc_id, sc_no)),
                ("Test_Env",                tc.test_environment),
                ("Test_Type",               tc.testing_type),
                ("Scenario_Type",           tc.scenario_type),
                ("Remarks",                 _remarks_bullets(tc)),
                ("Module",                  _module_alpha_only(tc.module)),
            ]

            table = doc.add_table(rows=len(rows), cols=2)
            table.style = "Table Grid"
            for ri, (label, val) in enumerate(rows):
                row = table.rows[ri]
                lc = row.cells[0]; lc.width = Inches(2.0)
                lr = lc.paragraphs[0].add_run(label)
                lr.font.bold = True; lr.font.size = Pt(9)
                vr = row.cells[1].paragraphs[0].add_run(str(val))
                vr.font.size = Pt(9)

            doc.add_paragraph()

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()