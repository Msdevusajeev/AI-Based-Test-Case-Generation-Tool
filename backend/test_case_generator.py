import re
import logging
from difflib import SequenceMatcher
from typing import List, Tuple, Dict

from models import TestCase, DocumentChunk
from constants import (
    MODULE_KEYWORDS, FUNCTIONAL_VERBS, SECURITY_KEYWORDS,
    PERFORMANCE_KEYWORDS, INTEGRATION_KEYWORDS, VALIDATION_ACTION_WORDS,
    BOUNDARY_TRIGGERS, STEP_TEMPLATES, INPUT_TEMPLATES,
    PRECONDITION_TEMPLATES, EXPECTED_OUTCOME_TEMPLATES,
)
from config import DEDUP_THRESHOLD

logger = logging.getLogger(__name__)

# ─── MODAL VERB CLEANER ───────────────────────────────────────────────────────

# Modal verbs that should NOT appear in test case descriptions / objectives
_MODAL_PATTERN = re.compile(
    r'\b(shall|should|must|may|can|will|would|could|might)\s+',
    re.IGNORECASE
)

def _clean_modal(text: str) -> str:
    """
    Removes modal verbs (shall, must, should, can, will, may) from a phrase.
    Used to produce clean, professional test case objectives and step descriptions.

    Examples:
      "shall allow users to login"  → "allow users to login"
      "must validate credentials"   → "validate credentials"
      "can display the dashboard"   → "display the dashboard"
    """
    cleaned = _MODAL_PATTERN.sub('', text).strip()
    # Capitalise first letter
    return cleaned[0].upper() + cleaned[1:] if cleaned else text

# ─── REQUIREMENT SIGNAL FILTER ───────────────────────────────────────────────
# Only sentences containing these keywords are treated as actual requirements.
# Everything else (headings, descriptions, notes, references) is skipped.

_REQ_SIGNALS = re.compile(
    r'\b(shall|must|should|will not|shall not|must not|'
    r'allow|enable|prevent|restrict|validate|calculate|'
    r'display|render|show|submit|process|return|create|update|delete|'
    r'search|filter|sort|authenticate|authorise|authorize|'
    r'notify|generate|export|import|upload|download|'
    r'verify|confirm|reject|approve|support|provide|ensure|'
    r'detect|monitor|log|record|send|receive|assign|track|'
    r'handle|manage|store|retrieve|compute|enforce|require|'
    r'permit|forbid|encrypt|hash|mask|redirect|trigger)\b',
    re.IGNORECASE
)

def _is_requirement_sentence(sentence: str) -> bool:
    """
    Returns True only if the sentence contains requirement-indicating language.
    Filters out: headings, descriptions, notes, references, page numbers,
    table headers, introductory paragraphs, and pure nouns/labels.
    """
    s = sentence.strip()
    # Too short to be a requirement
    if len(s.split()) < 5:
        return False
    # Looks like a heading (ends with colon, no verb)
    if s.endswith(':'):
        return False
    # Looks like a page number or reference code only
    if re.match(r'^[\d\.\s]+$', s):
        return False
    # Must contain at least one requirement signal word
    return bool(_REQ_SIGNALS.search(s))

# ─── NLP SETUP ───────────────────────────────────────────────────────────────

_NLP = None

def get_nlp():
    global _NLP
    if _NLP is not None:
        return _NLP
    try:
        import spacy
        _NLP = spacy.load("en_core_web_sm", disable=["ner", "lemmatizer"])
        logger.info("spaCy en_core_web_sm loaded")
    except Exception:
        try:
            from spacy.lang.en import English
            _NLP = English()
            _NLP.add_pipe("sentencizer")
            logger.info("spaCy blank English + sentencizer loaded")
        except Exception:
            _NLP = None
            logger.warning("spaCy not available — falling back to regex sentence splitting")
    return _NLP


def is_spacy_available() -> bool:
    try:
        import spacy
        return True
    except ImportError:
        return False


# ─── SENTENCE EXTRACTION ─────────────────────────────────────────────────────

def extract_requirement_sentences(text: str) -> List[str]:
    """
    Splits text into sentences and returns ONLY sentences that contain
    actual requirement language (shall, must, should, allow, validate, etc.).
    Skips headings, notes, descriptions, references, and general prose.
    """
    nlp = get_nlp()
    if nlp is not None:
        try:
            doc = nlp(text)
            raw_sentences = [sent.text.strip() for sent in doc.sents]
        except Exception:
            raw_sentences = re.split(r'(?<=[.!?])\s+', text)
    else:
        raw_sentences = re.split(r'(?<=[.!?])\s+', text)

    # Filter 1: only sentences with requirement signal words
    req_sentences = [s.strip() for s in raw_sentences if _is_requirement_sentence(s.strip())]

    # Filter 2: deduplicate exact matches
    seen, unique = set(), []
    for s in req_sentences:
        if s.lower() not in seen:
            seen.add(s.lower())
            unique.append(s)

    # Fallback: if the filter removed everything (e.g. the whole block is
    # one long sentence), return any sentence with minimum length
    if not unique:
        unique = [s.strip() for s in raw_sentences if len(s.split()) >= 5]

    return unique if unique else [text[:500]]


# ─── SUBJECT / ACTION EXTRACTION ─────────────────────────────────────────────

def extract_subject(sentence: str) -> str:
    nlp = get_nlp()
    if nlp is not None:
        try:
            doc = nlp(sentence)
            for chunk in doc.noun_chunks:
                if chunk.root.dep_ in ("nsubj", "nsubjpass"):
                    return chunk.text.strip()
            for chunk in doc.noun_chunks:
                return chunk.text.strip()
        except (ValueError, AttributeError):
            pass
    match = re.search(
        r'\b(the system|the user|the application|the module|the service|'
        r'the platform|the database|the api|the interface|the admin)\b',
        sentence, re.IGNORECASE
    )
    if match:
        return match.group(0)
    words = sentence.split()
    return " ".join(words[:min(4, len(words))])


def extract_action(sentence: str) -> str:
    """
    Extracts the action phrase from a requirement sentence.
    - Removes the 70-char hard cut (was truncating long actions)
    - Strips modal verbs (shall/must/can/will) from the result
      so actions read as plain verbs: "allow login" not "shall allow login"
    """
    lower = sentence.lower()
    # Find the first functional verb in the sentence
    for verb in FUNCTIONAL_VERBS:
        if verb in lower:
            idx = lower.find(verb)
            # Take from the verb to end of sentence (cut at . ; newline only)
            fragment = sentence[idx:]
            fragment = re.split(r'[.;\n]', fragment)[0].strip()
            # Remove modal verbs from the extracted action
            fragment = _clean_modal(fragment)
            return fragment if len(fragment) > 3 else verb
    # Regex: modal + verb fallback
    match = re.search(r'\b(shall|must|should|will|can)\s+(\w+)', sentence, re.IGNORECASE)
    if match:
        return match.group(2)          # return just the main verb, no modal
    nlp = get_nlp()
    if nlp is not None:
        doc = nlp(sentence)
        for token in doc:
            if token.pos_ == "VERB" and token.dep_ in ("ROOT", "relcl", "advcl"):
                fragment = sentence[token.idx:].split(".")[0].strip()
                return _clean_modal(fragment)
    return "perform the specified operation"


# ─── ASSIGNMENT FUNCTIONS ─────────────────────────────────────────────────────

def assign_priority(req_type: str, scenario_type: str, testing_type: str) -> str:
    if req_type == "functional" and scenario_type == "normal" and testing_type in ("validation", "integration"):
        return "P1"
    if req_type == "functional" and scenario_type == "boundary":
        return "P1"
    if req_type == "functional" and scenario_type == "normal":
        return "P1"
    if req_type == "non-functional" and scenario_type == "normal":
        return "P2"
    if scenario_type in ("edge", "robustness"):
        return "P2"
    if req_type == "non-functional" and scenario_type in ("boundary", "edge"):
        return "P3"
    return "P2"


def assign_methodology(sentence: str, scenario_type: str) -> str:
    lower = sentence.lower()
    if any(k in lower for k in SECURITY_KEYWORDS):
        return "Security Testing"
    if any(k in lower for k in PERFORMANCE_KEYWORDS):
        return "Performance Testing"
    return {
        "normal": "Black Box Testing",
        "boundary": "Boundary Value Analysis",
        "edge": "Equivalence Partitioning",
        "robustness": "Error Guessing",
    }[scenario_type]


def assign_testing_type(sentence: str, module: str) -> str:
    lower = sentence.lower()
    # Count module keyword hits
    module_hits = sum(1 for m in MODULE_KEYWORDS if m.lower() in lower)
    if module_hits >= 2 or any(k in lower for k in INTEGRATION_KEYWORDS):
        return "integration"
    if any(k in lower for k in VALIDATION_ACTION_WORDS):
        return "validation"
    return "verification"


def assign_environment(testing_type: str) -> str:
    return {
        "verification": "Dev",
        "validation": "UAT",
        "integration": "QA",
    }.get(testing_type, "QA")


# ─── REMARKS GENERATION ───────────────────────────────────────────────────────

def generate_remarks(sentence: str, req_id: str, notes_context: str = "",
                     scenario_type: str = "normal", input_source: str = "SRS") -> str:
    """
    Stores structured remark data as pipe-separated items.
    The output_generator._remarks_bullets() will format this as bullets (Req 8).
    Stored items are raw facts — no test-basis lines, no bullet prefixes here.
    """
    lower = sentence.lower()
    items = []

    # Document-level notes (enum defs, cross-refs) — strip test-basis
    if notes_context and notes_context.strip():
        parts = re.split(r'\s*\|\s*', notes_context.strip())
        for p in parts:
            p = p.strip()
            if p and not re.search(
                r'test\s+basis|input\s+values\s+derived|srs\s+requirement\s+\w',
                p, re.IGNORECASE
            ):
                items.append(p)

    # Input source (Req 4)
    if input_source == "ICD":
        items.append("derived from icd: Input values not explicitly defined in SRS — derived from ICD signal definitions")

    # Analysis observations
    if not any(k in lower for k in BOUNDARY_TRIGGERS):
        items.append("Note: No explicit boundary values in SRS — define min/max constraints before execution")

    if any(k in lower for k in SECURITY_KEYWORDS):
        items.append("Security: PII/security risk — ensure data masking in test environment")

    if any(w in lower for w in ["payment", "card", "bank", "billing", "invoice", "transaction", "credit"]):
        items.append("Compliance: PCI-DSS — use tokenised/synthetic test data only")

    if any(k in lower for k in INTEGRATION_KEYWORDS):
        items.append("Integration: External system dependency — mock/stub required")

    if any(w in lower for w in ["concurrent", "parallel", "simultaneous", "race", "multi-user"]):
        items.append("Risk: Race condition possible — concurrency testing recommended")

    if "error" not in lower and "fail" not in lower and "invalid" not in lower and "reject" not in lower:
        items.append("Coverage: No error handling path in SRS — negative scenario coverage assumed")

    return " | ".join(items)


# ─── DEPENDENCY RESOLUTION ────────────────────────────────────────────────────

def resolve_dependencies(scenario_type: str, previous: List[TestCase], req_id: str) -> str:
    """Requirement 10: Depends On = TC_ID + Scenario No concatenated."""
    if scenario_type == "normal":
        return "None"
    normals = [
        (tc.test_case_id, tc.scenario_id) for tc in previous
        if tc.scenario_type == "normal" and tc.traceability_req_id == req_id
    ]
    if normals:
        tc_id, sc_id = normals[-1]
        return f"{tc_id}_{sc_id}"
    return "None"


# ─── CORE GENERATION ─────────────────────────────────────────────────────────

# ─── DECISION TABLE ENGINE ────────────────────────────────────────────────────
# Detects requirements that contain a decision table (SC_N columns with
# Input_N / Output_N rows) and generates one precise test case per scenario
# instead of the generic normal/boundary/edge/robustness pattern.

_SC_PATTERN     = re.compile(r'\bSC[_\-]?\d+\b', re.IGNORECASE)
_INPUT_PATTERN  = re.compile(r'\bInput[_\-]?\d+\b', re.IGNORECASE)
_OUTPUT_PATTERN = re.compile(r'\bOutput[_\-]?\d+\b', re.IGNORECASE)


def _detect_decision_table(content: str) -> bool:
    """
    Returns True if the requirement content contains a decision table.
    Signal: 2+ SC_N column headers + Input_N rows + Output_N rows.
    """
    sc_count = len(_SC_PATTERN.findall(content))
    return (
        sc_count >= 2
        and bool(_INPUT_PATTERN.search(content))
        and bool(_OUTPUT_PATTERN.search(content))
    )


def _split_table_row(line: str) -> list:
    """
    Splits a table row into cells.
    Handles: tab-separated, pipe-separated (DOCX), multi-space-separated.
    Strips empty cells and leading/trailing whitespace.
    """
    # Pipe-separated (DOCX table export: "Input_1 | Tail Low | TRUE | TRUE")
    if '|' in line:
        parts = [p.strip() for p in line.split('|')]
        return [p for p in parts if p]
    # Tab-separated
    if '\t' in line:
        return [p.strip() for p in line.split('\t') if p.strip()]
    # Multi-space-separated (2+ spaces as column delimiter)
    parts = re.split(r' {2,}', line.strip())
    if len(parts) >= 2:
        return [p.strip() for p in parts if p.strip()]
    # Single-space: used as fallback — split on known value tokens
    # (TRUE/FALSE/Active/Inactive at end of line)
    return [p.strip() for p in line.split() if p.strip()]


def _parse_decision_table(content: str) -> dict:
    """
    Parses a decision table from requirement content.

    Robust against multiple formats:
      Tab-separated    : Input_1\tTail Low\tTRUE\tTRUE\tTRUE\tFALSE
      Pipe-separated   : Input_1 | Tail Low | TRUE | TRUE | TRUE | FALSE
      Multi-space      : Input_1  Tail Low  TRUE  TRUE  TRUE  FALSE

    Returns:
      { "SC_1": { "inputs": {"Name": "value"}, "outputs": {"Name": "value"} }, ... }
    """
    sc_headers = _SC_PATTERN.findall(content)
    if not sc_headers:
        return {}

    # Deduplicate SC headers preserving order
    seen, unique_sc = set(), []
    for sc in sc_headers:
        key = sc.upper()
        if key not in seen:
            seen.add(key)
            unique_sc.append(sc)
    sc_headers = unique_sc
    n_sc = len(sc_headers)

    scenarios = {sc: {"inputs": {}, "outputs": {}} for sc in sc_headers}

    for line in content.splitlines():
        raw = line.strip()
        if not raw:
            continue

        # ── Input row ────────────────────────────────────────────────────────
        inp_m = re.match(r'Input[_\-]?\d+[\s\|]+(.+)', raw, re.IGNORECASE)
        if inp_m:
            rest  = inp_m.group(1).strip()
            cells = _split_table_row(rest)
            # cells[0] = input name, cells[1..] = one value per SC column
            if len(cells) >= 2:
                name = cells[0]
                for i, sc in enumerate(sc_headers):
                    if i + 1 < len(cells):
                        scenarios[sc]["inputs"][name] = cells[i + 1]
            continue

        # ── Output row ───────────────────────────────────────────────────────
        out_m = re.match(r'Output[_\-]?\d+[\s\|]+(.+)', raw, re.IGNORECASE)
        if out_m:
            rest  = out_m.group(1).strip()
            cells = _split_table_row(rest)
            if len(cells) >= 2:
                name = cells[0]
                for i, sc in enumerate(sc_headers):
                    if i + 1 < len(cells):
                        scenarios[sc]["outputs"][name] = cells[i + 1]

    # ── Fallback: if standard parsing found no inputs, try column-by-column ──
    # Handles when Input_N label is on a separate line from values
    if all(not d["inputs"] for d in scenarios.values()):
        scenarios = _parse_decision_table_by_columns(content, sc_headers)

    return scenarios


def _parse_decision_table_by_columns(content: str, sc_headers: list) -> dict:
    """
    Fallback parser: builds the table by scanning ALL lines and mapping
    values to SC columns positionally.
    Used when Input_N and values are not on the same line.
    """
    scenarios = {sc: {"inputs": {}, "outputs": {}} for sc in sc_headers}
    lines = [l.strip() for l in content.splitlines() if l.strip()]

    # Find the header line containing SC_N labels
    header_idx = next(
        (i for i, l in enumerate(lines) if _SC_PATTERN.search(l)), None
    )
    if header_idx is None:
        return scenarios

    # Map SC label → column index within the header line
    header_cells = _split_table_row(lines[header_idx])
    sc_col_map = {}
    for ci, cell in enumerate(header_cells):
        m = _SC_PATTERN.match(cell.strip())
        if m:
            sc_col_map[cell.strip()] = ci

    for line in lines[header_idx + 1:]:
        cells = _split_table_row(line)
        if len(cells) < 2:
            continue
        inp_m = re.match(r'Input[_\-]?\d+', cells[0], re.IGNORECASE)
        out_m = re.match(r'Output[_\-]?\d+', cells[0], re.IGNORECASE)
        if not inp_m and not out_m:
            continue
        if len(cells) < 2:
            continue
        name = cells[1] if len(cells) > 1 else cells[0]
        for sc, col_idx in sc_col_map.items():
            if col_idx < len(cells):
                val = cells[col_idx]
                if inp_m:
                    scenarios[sc]["inputs"][name] = val
                else:
                    scenarios[sc]["outputs"][name] = val

    return scenarios


def _all_outputs_true(outputs: dict) -> bool:
    """Returns True when ALL output values are TRUE/Active/1/Yes."""
    positive = {"true", "active", "1", "yes", "enabled", "set"}
    return all(str(v).strip().lower() in positive for v in outputs.values())


def _generate_decision_table_tcs(
    req_id:    str,
    scenarios: dict,
    chunk:     "DocumentChunk",
    tc_counters: Dict[str, int],
    sc_counter:  int,
    review_points: dict,
) -> Tuple[List["TestCase"], int]:
    """
    Generates one test case per decision table scenario (SC_1, SC_2 …).

    Scenario type assignment:
      - All outputs TRUE/Active  → normal    (all conditions met — positive case)
      - Any output FALSE/Inactive → edge     (one or more conditions violated)

    Priority:
      - Normal positive case → P1
      - Negative / edge cases → P1 (decision table TCs are always high priority
        because they encode the exact acceptance criteria)

    Design methodology → Decision Table Testing (cause-effect analysis).
    """
    results: List["TestCase"] = []

    for sc_id, data in scenarios.items():
        inputs_dict  = data.get("inputs",  {})
        outputs_dict = data.get("outputs", {})

        if not inputs_dict and not outputs_dict:
            continue

        # Determine scenario type from outputs
        positive      = _all_outputs_true(outputs_dict)
        scenario_type = "normal" if positive else "edge"

        # Build precise inputs list: "Name: Value"
        inputs_list = [f"{name}: {value}" for name, value in inputs_dict.items()]

        # Build expected outcome from outputs
        outcome_parts = [f"{name} = {value}" for name, value in outputs_dict.items()]
        expected      = "; ".join(outcome_parts)

        # Build precise test steps
        steps = ["1. Initialise system to a known clean state"]
        for j, (name, value) in enumerate(inputs_dict.items(), start=2):
            steps.append(f"{j}. Set {name} = {value}")
        trigger_step = len(steps) + 1
        steps.append(f"{trigger_step}. Trigger the Altitude direction logic module evaluation")
        verify_step = trigger_step + 1
        for k, (out_name, out_val) in enumerate(outputs_dict.items()):
            steps.append(f"{verify_step + k}. Verify {out_name} is {out_val}")
        steps.append(
            f"{verify_step + len(outputs_dict)}. "
            f"Confirm no unexpected side effects or state changes occur"
        )

        # Build preconditions
        preconds = [
            f"System is initialised in the {chunk.module} module",
            "All input signals are controllable in the test environment",
            "Previous test state has been cleared",
        ]
        # Add enum notes if present
        for name, value in inputs_dict.items():
            lower_val = value.lower()
            if lower_val in ("active", "inactive", "in active"):
                preconds.append(
                    f"{name} accepts enum values: Active / Inactive"
                )
                break

        # Remarks explain why this scenario was generated
        notes_ctx = getattr(chunk, "notes_context", "")
        notes_suffix = f" | Document context: {notes_ctx}" if notes_ctx else ""
        test_basis = (
            f" | Test basis: SRS requirement {req_id}. "
            f"Input values derived from SRS/ICD signal definitions."
        )

        active_conditions = [
            f"{name} = {value}"
            for name, value in inputs_dict.items()
            if str(value).strip().lower() in ("true", "active", "1", "yes")
        ]
        inactive_conditions = [
            f"{name} = {value}"
            for name, value in inputs_dict.items()
            if str(value).strip().lower() not in ("true", "active", "1", "yes")
        ]

        if positive:
            remarks = (
                f"DECISION TABLE — {sc_id} is the POSITIVE scenario: "
                f"all conditions met. Active inputs: "
                + "; ".join(active_conditions) + ". "
                f"Verifies that the output is correctly set to TRUE when all "
                f"required conditions are simultaneously active."
                f"{test_basis}{notes_suffix}"
            )
        else:
            remarks = (
                f"DECISION TABLE — {sc_id} is a NEGATIVE scenario: "
                f"condition(s) not met. Inactive/violated inputs: "
                + "; ".join(inactive_conditions) + ". "
                f"Verifies that the output correctly remains FALSE when at "
                f"least one required condition is violated."
                f"{test_basis}{notes_suffix}"
            )

        tc_counters["UT"] += 1
        tc_id = f"TC_UT_{tc_counters['UT']:03d}"

        results.append(TestCase(
            traceability_req_id  = req_id,
            test_case_id         = tc_id,
            scenario_id          = f"SC_{sc_counter:03d}",
            priority             = "P1",
            objective            = (
                f"Verify Altitude Alert Condition Enabled output for {sc_id}: "
                f"{expected}"
            ),
            preconditions        = preconds,
            test_steps           = steps,
            inputs               = inputs_list,
            design_methodology   = "Decision Table Testing",
            dependent_test_cases = "None",
            expected_outcome     = (
                f"For scenario {sc_id}: {expected}. "
                f"The logic module correctly evaluates all input conditions "
                f"and sets the output as per the decision table."
            ),
            test_environment     = "Dev",
            remarks              = remarks,
            module               = chunk.module,
            requirement_type     = chunk.requirement_type,
            scenario_type        = scenario_type,
            testing_type         = "verification",
        ))
        sc_counter += 1

    logger.info(
        f"Decision table: {req_id} → {len(results)} TCs "
        f"({len(scenarios)} scenarios)"
    )
    return results, sc_counter


# ─── MC/DC ENGINE ─────────────────────────────────────────────────────────────
# Modified Condition / Decision Coverage (MC/DC) — DO-178C / avionics standard
#
# MC/DC requires for EACH condition C in a decision:
#   There exist two test cases that differ ONLY in the value of C,
#   and the DECISION (output) changes between those two test cases.
#   This proves each condition INDEPENDENTLY affects the outcome.
#
# For pure AND-logic with n conditions, MC/DC needs exactly n+1 test cases:
#   TC_baseline : all conditions at required values  → output = True
#   TC_flip_i   : condition_i flipped, rest unchanged → output = False
#
# For OR-logic with n conditions, MC/DC needs exactly n+1 test cases:
#   TC_baseline : all conditions at their FALSE values → output = False
#   TC_flip_i   : condition_i set to True, rest unchanged → output = True
#
# The independence pair for condition_i is always (TC_baseline, TC_flip_i).
#
# Numeric conditions: use ICD range data when available; otherwise use
# explicit boundary values (valid vs invalid) derived from the requirement.

_COND_COVERAGE_PATTERN = re.compile(
    r'when\s+all\s+(?:the\s+)?following\s+(?:conditions\s+)?(?:are\s+)?(?:met|true|satisfied|fulfilled)',
    re.IGNORECASE
)
_OR_PATTERN = re.compile(
    r'when\s+any\s+(?:one\s+)?(?:of\s+)?(?:the\s+)?following\s+(?:conditions\s+)?(?:are\s+)?(?:met|true|satisfied|fulfilled)',
    re.IGNORECASE
)


def _detect_conditional_requirement(content: str) -> bool:
    """True when requirement uses 'when all/any following conditions are met' structure."""
    return bool(_COND_COVERAGE_PATTERN.search(content)) or bool(_OR_PATTERN.search(content))


def _get_flip_value(name: str, value: str, full_content: str) -> str:
    """
    Returns the MC/DC flip value for a condition — the value that makes
    this condition FALSE (for AND-logic) or TRUE (for OR-logic).

    For boolean/enum: uses known opposites or Notes-declared enum values.
    For numeric: uses ICD range data (e.g. 'Range: -100 to 100') to produce
                 a valid out-of-range value that violates the condition.
    Handles comparison operators: < > <= >= → inverts the operator.
    """
    # Comparison operator flip: invert the operator direction
    _cmp = {'< ': '>= ', '> ': '<= ', '<= ': '> ', '>= ': '< '}
    for op, flipped in _cmp.items():
        if value.startswith(op):
            return flipped + value[len(op):]
    # Also handle without trailing space
    _cmp2 = {'<': '>= ', '>': '<= '}
    for op, flipped in _cmp2.items():
        if value.startswith(op) and not value.startswith('<=') and not value.startswith('=>'):
            return flipped + value[len(op):].strip()

    lv = value.lower().strip()

    # Boolean flip
    if lv in ('true', 'yes', '1', 'enabled'):  return 'False'
    if lv in ('false', 'no', '0', 'disabled'): return 'True'

    # Enum: look for Notes section declaring enum values
    key = name.split()[-1]
    em = re.search(
        rf'(?:{re.escape(name)}|{re.escape(key)})\s+is\s+an\s+enum\s+with\s+\d+\s+values?\s+(\w+)\s+and\s+(\w+)',
        full_content, re.IGNORECASE
    )
    if em:
        v1, v2 = em.group(1), em.group(2)
        return v2 if value.lower() == v1.lower() else v1

    # Numeric: check if value is a number, then look for ICD range to find
    # a value outside the required range → violates the condition
    try:
        num_val = float(value)
        # Look for "Name | Integer/Float | -X to Y" range in ICD table
        range_m = re.search(
            rf'{re.escape(name)}\s*\|\s*\w+\s*\|\s*([-\d.]+)\s+to\s+([-\d.]+)',
            full_content, re.IGNORECASE
        )
        if range_m:
            lo, hi = float(range_m.group(1)), float(range_m.group(2))
            # Flip value = just outside the valid range
            flip = lo - 1 if num_val > lo else hi + 1
            return str(int(flip) if flip == int(flip) else flip)
        else:
            # No range info: use 0 if value != 0, else use -1
            flip_num = 0 if num_val != 0 else -1
            return str(flip_num)
    except ValueError:
        pass

    # Common string opposites
    return {
        'active':   'Inactive', 'inactive': 'Active',
        'high':     'Low',      'low':      'High',
        'on':       'Off',      'off':      'On',
        'enabled':  'Disabled', 'disabled': 'Enabled',
        'set':      'Reset',    'reset':    'Set',
        'open':     'Closed',   'closed':   'Open',
        'valid':    'Invalid',  'invalid':  'Valid',
    }.get(lv, f'Not_{value}')


def _parse_conditional_requirement(content: str) -> dict:
    """
    Parses a conditional requirement into:
      - logic_type:     'AND' or 'OR'
      - output_name:    the output signal name
      - output_true_val / output_false_val
      - conditions:     list of { name, required_val, flip_val }

    Handles all common SRS formats:
      - Bullet list:    "- Radio Altitude is True"
      - Inline and/or:  "when X is True and Y is False"
      - Equality:       "when Signal = Value"  or  "Signal = True"
      - Comparison:     "when Value < 500"  or  "Signal >= threshold"
      - Colon format:   "Signal: Value"
    """
    result = {
        "logic_type":       "AND",
        "output_name":      "",
        "output_true_val":  "True",
        "output_false_val": "False",
        "conditions":       [],
    }

    # ── Detect AND vs OR logic ────────────────────────────────────────────────
    if _OR_PATTERN.search(content):
        result["logic_type"] = "OR"

    # ── Extract output signal name ────────────────────────────────────────────
    # Format: "shall set <name> to <True|Enabled|Active|1>"
    _QUOTE_CHARS = r'[\u2018\u2019\u201c\u201d\"\' ]'
    for pat in [
        r'shall\s+set\s+(?:the\s+)?([\w\s]{3,60}?)\s+to\s+' + _QUOTE_CHARS + r'?(True|Enabled|Active|Green|Valid|1)' + _QUOTE_CHARS + r'?',
        r'(?:activate|enable|assert)\s+(?:the\s+)?([\w\s]{3,60})',
        r'([\w_]{3,60})\s*=\s*(True|Enabled|Enable|Active|Green|Valid|1)\b',
    ]:
        m = re.search(pat, content, re.IGNORECASE)
        if m:
            result["output_name"]     = m.group(1).strip().rstrip("'")
            result["output_true_val"] = m.group(2) if m.lastindex >= 2 else "True"
            break

    otherwise_m = re.search(
        r'otherwise\s+(?:set\s+to\s+)?[\u2018\u2019\u201c\u201d"\'](\w+)[\u2018\u2019\u201c\u201d"\']',
        content, re.IGNORECASE
    )
    if not otherwise_m:
        otherwise_m = re.search(r'otherwise\s+(?:set\s+to\s+)?(\w+)', content, re.IGNORECASE)
    if otherwise_m:
        result["output_false_val"] = otherwise_m.group(1)

    # ── Isolate the conditions block ──────────────────────────────────────────
    split_pat = _OR_PATTERN if result["logic_type"] == "OR" else _COND_COVERAGE_PATTERN
    parts = split_pat.split(content)
    cond_text = parts[1] if len(parts) > 1 else content

    # Also handle inline "when X ... and Y ... and Z" (no bullet list)
    when_m = re.search(r'\bwhen\b(.+)$', cond_text, re.IGNORECASE | re.DOTALL)
    if when_m:
        inline = when_m.group(1).strip()
        # Split inline conditions on " and " or " or "
        # but keep each clause as a candidate condition line
        inline_parts = re.split(r'\b(?:and|or)\b', inline, flags=re.IGNORECASE)
        if len(inline_parts) > 1:
            cond_text = "\n".join(inline_parts)

    # ── Parse Notes section for enum declarations ────────────────────────────
    # Handles single and compound Notes formats:
    #   "Signal is an enum with N values A, B and C"
    #   "Signal1 and Signal2 are an enum with N values A and B"
    enum_values: dict = {}
    for note_line in cond_text.splitlines():
        # Format: "SignalA and SignalB are an enum with N values X and Y"
        multi_m = re.search(
            r'(.+?)\s+and\s+(.+?)\s+are\s+an\s+enum\s+with\s+\d+\s+values?\s+(.+)$',
            note_line, re.IGNORECASE
        )
        if multi_m:
            raw_vals = re.split(r',\s*|\s+and\s+', multi_m.group(3).strip().rstrip('.'))
            raw_vals = [v.strip().strip('\u2018\u2019\u201c\u201d"\' ') for v in raw_vals if v.strip()]
            for sig_raw in [multi_m.group(1), multi_m.group(2)]:
                sig_name = re.sub(r'^[Tt]he\s+', '', sig_raw.strip()).lower()
                if raw_vals:
                    enum_values[sig_name] = raw_vals
            continue
        # Format: "Signal is an enum with N values A, B and C"
        em = re.search(
            r'(.+?)\s+is\s+an\s+enum\s+with\s+\d+\s+values?\s+(.+)$',
            note_line, re.IGNORECASE
        )
        if em:
            sig_name = re.sub(r'^[Tt]he\s+', '', em.group(1).strip()).lower()
            raw_vals = re.split(r',\s*|\s+and\s+', em.group(2).strip().rstrip('.'))
            raw_vals = [v.strip().strip('\u2018\u2019\u201c\u201d"\' ') for v in raw_vals if v.strip()]
            if raw_vals:
                enum_values[sig_name] = raw_vals


    seen_names: set = set()

    # Pre-expand "Either X is Y or Z is W" into two separate lines
    expanded_lines = []
    for raw_line in cond_text.splitlines():
        stripped = raw_line.strip().lstrip('*-•→►▶\u2022·').strip()
        # Detect "Either X is Y or Z is W" pattern and split into two lines
        either_m = re.match(
            r'(?:either\s+)?(.+?\s+is\s+[\u2018\u2019\u201c\u201d"\' ]?\w+[\u2018\u2019\u201c\u201d"\' ]?)'
            r'\s+or\s+(.+?\s+is\s+[\u2018\u2019\u201c\u201d"\' ]?\w+[\u2018\u2019\u201c\u201d"\' ]?)\s*[,.]?$',
            stripped, re.IGNORECASE
        )
        if either_m:
            expanded_lines.append(either_m.group(1).strip())
            expanded_lines.append(either_m.group(2).strip())
        else:
            expanded_lines.append(raw_line)

    for raw_line in expanded_lines:
        line = raw_line.strip().lstrip('*-•→►▶\u2022·').strip()
        # Skip empty, notes headers, very short lines, output lines
        if not line or len(line) < 4:
            continue
        if re.match(r'notes?\s*:', line, re.IGNORECASE):
            continue
        if re.search(r'shall\s+set', line, re.IGNORECASE):
            continue
        if re.search(r'otherwise', line, re.IGNORECASE):
            continue
        # Skip Notes enum declarations (already parsed above)
        if re.search(r'is\s+an\s+enum\s+with', line, re.IGNORECASE):
            continue
        # Skip "and are an enum" lines
        if re.search(r'are\s+an\s+enum\s+with', line, re.IGNORECASE):
            continue

        # Strip surrounding quotes from the whole line first
        line_clean = line.strip('"\'‘’“”')

        name = val = None

        # Pattern 1: "Signal is 'Value'" or "Signal is Value" — quoted or bare
        # Accepts ANY word as value (not just known booleans) since we're in
        # the conditions block. Also handles "less than N", "greater than N".
        m = re.match(
            r'(.+?)\s+is\s+[\u2018\u2019\u201c\u201d\"\']*'
            r'(less\s+than|greater\s+than|not\s+available|[\w][\w\s]{0,30}?)' 
            r'[\u2018\u2019\u201c\u201d\"\' ]*[,.]?\s*$',
            line, re.IGNORECASE
        )
        if m:
            raw_name = m.group(1).strip()
            raw_val  = m.group(2).strip().strip('"\'‘’“”')
            if raw_val.lower().startswith('less than'):
                nums = re.findall(r'-?[\d.]+', raw_val)
                raw_val = f"< {nums[0]}" if nums else "< threshold"
            elif raw_val.lower().startswith('greater than'):
                nums = re.findall(r'-?[\d.]+', raw_val)
                raw_val = f"> {nums[0]}" if nums else "> threshold"
            # Filter out values that look like sentence fragments (> 4 words)
            if len(raw_val.split()) <= 4:
                name, val = raw_name, raw_val

        # Pattern 2: "Signal = Value" (with optional quotes)
        if not name:
            m = re.match(
                r'([\w][\w\s\.]{1,60})\s*=\s*[\u2018\u2019\u201c\u201d\"\']*([\w][\w\s]{0,30}?)[\u2018\u2019\u201c\u201d\"\' ]*[,.]?\s*$',
                line
            )
            if m and re.match(r'[A-Za-z]', m.group(1)):
                name = m.group(1).strip()
                val  = m.group(2).strip().strip('"\'‘’“”')

        # Pattern 3: "Signal < N" or "Signal >= N" comparisons
        if not name:
            m = re.match(
                r'([\w][\w\s\.]{1,60})\s*(<=|>=|<|>|==|!=)\s*([\u2018\u2019\u201c\u201d\"\']*[\w][\w\s]{0,20}[\u2018\u2019\u201c\u201d\"\']*)[,.]?\s*$',
                line
            )
            if m and re.match(r'[A-Za-z]', m.group(1)):
                name = m.group(1).strip()
                val  = f"{m.group(2)} {m.group(3).strip().strip(chr(39)+chr(34))}"

        # Pattern 4: "Signal: Value"
        if not name:
            m = re.match(
                r'([\w][\w\s\.]{1,60}):\s*[\u2018\u2019\u201c\u201d\"\']*([\w][\w\s]{0,20})[\u2018\u2019\u201c\u201d\"\']*[,.]?\s*$',
                line
            )
            if m and re.match(r'[A-Za-z]', m.group(1)):
                name = m.group(1).strip()
                val  = m.group(2).strip()

        if not name or not val:
            continue

        # Clean name: strip "The " prefix, collapse whitespace
        name = re.sub(r'^[Tt]he\s+', '', name).strip()
        name = re.sub(r'\s+', ' ', name)

        # Reject if name looks like a sentence (too many words)
        if len(name.split()) > 7:
            continue
        # Skip duplicate signals
        if name.lower() in seen_names:
            continue
        seen_names.add(name.lower())

        # Determine flip value — use Notes enum if available
        name_key = name.lower()
        if name_key in enum_values:
            enum_vals = enum_values[name_key]
            val_lower = val.lower()
            # Pick the first enum value that is NOT the current value
            flip_val = next(
                (v for v in enum_vals if v.lower() != val_lower),
                _get_flip_value(name, val, cond_text)
            )
        else:
            flip_val = _get_flip_value(name, val, cond_text)

        result["conditions"].append({
            "name":         name,
            "required_val": val,
            "flip_val":     flip_val,
            "enum_values":  enum_values.get(name_key, []),  # all valid values for this signal
        })

    # Sanity cap
    result["conditions"] = result["conditions"][:20]
    return result


def _generate_mcdc_tcs(
    req_id:        str,
    parsed:        dict,
    chunk:         "DocumentChunk",
    tc_counters:   Dict[str, int],
    sc_counter:    int,
    review_points: dict,
) -> Tuple[List["TestCase"], int]:
    """
    Generates MC/DC (Modified Condition / Decision Coverage) test cases.

    MC/DC Rule: For EACH condition C in the decision, there must exist
    an independence pair — two test cases where:
      1. Only C changes value between the two cases
      2. All other conditions remain the same
      3. The output (decision) changes as a result

    This proves each condition INDEPENDENTLY influences the output.

    For AND-logic (n conditions) → n+1 test cases:
      TC_baseline : ALL conditions at required values → output = True
      TC_flip_i   : condition_i flipped, rest unchanged → output = False
      Independence pair for condition_i = (TC_baseline, TC_flip_i)

    For OR-logic (n conditions) → n+1 test cases:
      TC_baseline : ALL conditions at their flip (FALSE) values → output = False
      TC_flip_i   : condition_i set to required (TRUE), rest unchanged → output = True
      Independence pair for condition_i = (TC_baseline, TC_flip_i)

    Each TC includes in its remarks:
      - Which condition is being independently exercised
      - The independence pair reference (TC_baseline ↔ TC_flip_i)
      - Input source (SRS / ICD)
    """
    conditions  = parsed["conditions"]
    output_name = parsed["output_name"] or "output"
    true_val    = parsed["output_true_val"]
    false_val   = parsed["output_false_val"]
    logic       = parsed.get("logic_type", "AND")

    if not conditions:
        return [], sc_counter

    results: List["TestCase"] = []
    notes_ctx = getattr(chunk, "notes_context", "")

    # ── Build MC/DC scenario table ────────────────────────────────────────────
    # Each row: { sc_label, kind, inputs{name:val}, output, independent_condition }

    if logic == "AND":
        # Baseline: all conditions at required values → output = True
        baseline_inputs = {c["name"]: c["required_val"] for c in conditions}
        baseline_output = true_val
        # Flip scenarios: one condition at flip_val, rest at required → output = False
        flip_scenarios = []
        for cond in conditions:
            flip_inputs = {c["name"]: (cond["flip_val"] if c["name"] == cond["name"]
                                       else c["required_val"]) for c in conditions}
            flip_scenarios.append({
                "inputs":     flip_inputs,
                "output":     false_val,
                "indep_cond": cond["name"],
                "from_val":   cond["required_val"],
                "to_val":     cond["flip_val"],
            })
    else:  # OR-logic
        # Baseline: all conditions at flip (false) values → output = False
        baseline_inputs = {c["name"]: c["flip_val"] for c in conditions}
        baseline_output = false_val
        # Flip scenarios: one condition at required (true), rest at flip → output = True
        flip_scenarios = []
        for cond in conditions:
            flip_inputs = {c["name"]: (cond["required_val"] if c["name"] == cond["name"]
                                       else c["flip_val"]) for c in conditions}
            flip_scenarios.append({
                "inputs":     flip_inputs,
                "output":     true_val,
                "indep_cond": cond["name"],
                "from_val":   cond["flip_val"],
                "to_val":     cond["required_val"],
            })

    # ── Generate TC_baseline first ────────────────────────────────────────────
    tc_counters["UT"] += 1
    baseline_tc_id = f"TC_UT_{tc_counters['UT']:03d}"
    baseline_sc_id = f"SC_{sc_counter:03d}"

    # Independence pairs summary for baseline remarks
    pairs_summary = "; ".join(
        f"{s['indep_cond']} independence → ({baseline_tc_id} ↔ TC_UT_{tc_counters['UT'] + i + 1:03d})"
        for i, s in enumerate(flip_scenarios)
    )

    # Build steps for baseline
    baseline_steps = ["1. Initialise the system to a known clean state and reset all signals"]
    for j, (name, val) in enumerate(baseline_inputs.items(), start=2):
        baseline_steps.append(f"{j}. Set {name} = {val}")
    t = len(baseline_steps) + 1
    baseline_steps += [
        f"{t}.   Trigger evaluation of the {logic}-decision for {req_id}",
        f"{t+1}. Read the value of {output_name}",
        f"{t+2}. Verify {output_name} = {baseline_output} (all conditions {'met' if logic == 'AND' else 'false'})",
        f"{t+3}. Confirm no unexpected side effects or state changes",
    ]

    # Input source detection
    input_source_note = (
        "• Input source: Values explicitly defined in SRS specification."
        if all(c["required_val"].lower() not in ("not_", "0", "-1")
               for c in conditions)
        else "• Input source: Values not fully defined in SRS — derived from ICD signal definitions."
    )

    baseline_remarks = (
        f"• MC/DC BASELINE ({logic}-logic) — {req_id}\n"
        f"• All {len(conditions)} conditions set to their required values → {output_name} = {baseline_output}\n"
        f"• Conditions (each evaluated independently):\n"
        + "\n".join(
            f"    - {c['name']} = {c['required_val']}"
            for c in conditions
        ) + "\n"
        f"• This TC is the reference for ALL independence pairs:\n"
        + "\n".join(
            f"  - {s['indep_cond']}: baseline (this TC) ↔ "
            f"TC_UT_{tc_counters['UT'] + i + 1:03d} "
            f"[{s['indep_cond']} changes {s['from_val']} → {s['to_val']}, output changes]"
            for i, s in enumerate(flip_scenarios)
        ) + "\n"
        f"• MC/DC satisfies DO-178C Level A/B requirement independence criterion\n"
        + (f"• Document context: {notes_ctx}" if notes_ctx else "")
        + f"\n{input_source_note}"
    )

    results.append(TestCase(
        traceability_req_id  = req_id,
        test_case_id         = baseline_tc_id,
        scenario_id          = baseline_sc_id,
        priority             = "P1",
        objective            = (
            f"[MC/DC BASELINE] Verify {output_name} = {baseline_output} "
            f"when ALL {len(conditions)} conditions are at required values "
            f"({logic}-logic, {req_id})"
        ),
        preconditions        = [
            f"System is initialised in the {chunk.module} module",
            "All input signals are independently controllable in the test environment",
            "Test environment supports individual condition isolation (MC/DC prerequisite)",
            f"Output signal '{output_name}' is observable and measurable",
            "Previous test state has been fully reset to baseline",
        ],
        test_steps           = baseline_steps,
        inputs               = [f"{name}: {val}" for name, val in baseline_inputs.items()],
        design_methodology   = "MC/DC Testing",
        dependent_test_cases = "None",
        expected_outcome     = (
            f"{output_name} = {baseline_output}. "
            f"{logic}-decision evaluates to {baseline_output} when all conditions are at required values."
        ),
        test_environment     = "Dev",
        remarks              = baseline_remarks,
        module               = chunk.module,
        requirement_type     = chunk.requirement_type,
        scenario_type        = "normal",
        testing_type         = "verification",
    ))
    sc_counter += 1

    # ── Generate one independence TC per condition ─────────────────────────────
    for i, sc in enumerate(flip_scenarios):
        tc_counters["UT"] += 1
        tc_id = f"TC_UT_{tc_counters['UT']:03d}"
        sc_id = f"SC_{sc_counter:03d}"

        steps = ["1. Initialise the system to a known clean state and reset all signals"]
        for j, (name, val) in enumerate(sc["inputs"].items(), start=2):
            marker = "  ← CHANGED (independence flip)" if name == sc["indep_cond"] else ""
            steps.append(f"{j}. Set {name} = {val}{marker}")
        t = len(steps) + 1
        steps += [
            f"{t}.   Trigger evaluation of the {logic}-decision for {req_id}",
            f"{t+1}. Read the value of {output_name}",
            f"{t+2}. Verify {output_name} = {sc['output']} "
            f"(because {sc['indep_cond']} = {sc['to_val']} violates condition)",
            f"{t+3}. Confirm independence: ONLY {sc['indep_cond']} differs from {baseline_tc_id}",
            f"{t+4}. Confirm no unexpected side effects or state changes",
        ]

        flip_remarks = (
            f"• MC/DC INDEPENDENCE TEST — condition: '{sc['indep_cond']}' ({req_id})\n"
            f"• Independence pair: {baseline_tc_id} (baseline) ↔ {tc_id} (this TC)\n"
            f"• Changed condition (independent flip):\n"
            f"    - {sc['indep_cond']} = {sc['from_val']} → {sc['to_val']}\n"
            f"• Unchanged conditions (identical to baseline):\n"
            + "\n".join(
                f"    - {c['name']} = {sc['inputs'][c['name']]}"
                for c in conditions
                if c['name'] != sc['indep_cond']
            ) + "\n"
            f"• Output change: {baseline_output} → {sc['output']} "
            f"(proves {sc['indep_cond']} independently controls the {logic}-decision)\n"
            f"• MC/DC criterion satisfied for '{sc['indep_cond']}': "
            f"unique independence pair ({baseline_tc_id}, {tc_id})\n"
            + (f"• Document context: {notes_ctx}\n" if notes_ctx else "")
            + f"{input_source_note}"
        )

        results.append(TestCase(
            traceability_req_id  = req_id,
            test_case_id         = tc_id,
            scenario_id          = sc_id,
            priority             = "P1",
            objective            = (
                f"[MC/DC] Verify '{sc['indep_cond']}' independently controls {output_name} "
                f"({sc['indep_cond']}={sc['to_val']} → {output_name}={sc['output']})"
            ),
            preconditions        = [
                f"System is initialised in the {chunk.module} module",
                "All input signals are independently controllable",
                f"Baseline TC {baseline_tc_id} has already been executed and passed",
                f"Only '{sc['indep_cond']}' will differ from the baseline configuration",
                f"Output signal '{output_name}' is observable and measurable",
            ],
            test_steps           = steps,
            inputs               = [f"{name}: {val}" for name, val in sc["inputs"].items()],
            design_methodology   = "MC/DC Testing",
            dependent_test_cases = baseline_tc_id,
            expected_outcome     = (
                f"{output_name} = {sc['output']}. "
                f"Changing only '{sc['indep_cond']}' from {sc['from_val']} to {sc['to_val']} "
                f"causes the {logic}-decision to change from {baseline_output} to {sc['output']}. "
                f"MC/DC independence criterion confirmed for '{sc['indep_cond']}'."
            ),
            test_environment     = "Dev",
            remarks              = flip_remarks,
            module               = chunk.module,
            requirement_type     = chunk.requirement_type,
            scenario_type        = "edge",
            testing_type         = "verification",
        ))
        sc_counter += 1

    logger.info(
        f"MC/DC: {req_id} ({logic}-logic) → {len(results)} TCs "
        f"(1 baseline + {len(conditions)} independence tests)"
    )
    return results, sc_counter
    return results, sc_counter


def generate_for_chunk(
    chunk: DocumentChunk,
    tc_counters: Dict[str, int],
    sc_counter: int,
    review_points: dict,
    req_to_first_tc: Dict[str, str] = None,
) -> Tuple[List[TestCase], int]:
    """
    Generates test cases for all sentences in a chunk.

    Parent-child awareness:
    - Sub-requirement chunks include parent context in content
    - Sub-requirement TCs reference the parent's first normal TC in dependent_test_cases
    - Parent chunks with children get one extra integration TC combining all children

    Returns (test_cases, updated_sc_counter).
    """
    if req_to_first_tc is None:
        req_to_first_tc = {}

    primary_req_id = chunk.requirement_ids[0] if chunk.requirement_ids else "REQ-001"
    raw_content    = chunk.content

    # ── MC/DC fast-path ──────────────────────────────────────────────────────
    # "shall set X to True when ALL/ANY following conditions are met"
    # → generate MC/DC baseline + one independence TC per condition
    if _detect_conditional_requirement(raw_content):
        parsed_cond = _parse_conditional_requirement(raw_content)
        if parsed_cond["conditions"]:
            return _generate_mcdc_tcs(
                primary_req_id, parsed_cond, chunk,
                tc_counters, sc_counter, review_points
            )

    # ── Decision table fast-path ──────────────────────────────────────────────
    # If the requirement contains a pre-built decision table (SC_N / Input_N / Output_N),
    # generate one precise TC per scenario column.
    if _detect_decision_table(raw_content):
        scenarios = _parse_decision_table(raw_content)
        if scenarios:
            return _generate_decision_table_tcs(
                primary_req_id, scenarios, chunk,
                tc_counters, sc_counter, review_points
            )

    # ── Standard generation path (no decision table found) ───────────────────
    # For sub-requirements: strip the [Parent...] prefix for sentence extraction
    # but keep it available for context in remarks
    if chunk.is_sub_req and raw_content.startswith("[Parent"):
        # Extract just the sub-requirement content for sentence processing
        sub_marker = f"[Sub-Requirement {chunk.requirement_ids[0]}]: "
        if sub_marker in raw_content:
            processing_content = raw_content.split(sub_marker, 1)[1]
        else:
            processing_content = raw_content
    else:
        processing_content = raw_content

    sentences = extract_requirement_sentences(processing_content)
    results: List[TestCase] = []

    # If RP2 is off, only generate 'normal' scenario
    scenario_types = (
        ("normal", "boundary", "edge", "robustness")
        if review_points.get("rp2", True)
        else ("normal",)
    )

    prefix_map = {"validation": "VD", "integration": "IT", "verification": "UT"}

    # Primary requirement ID for this chunk — used as the traceability ID
    # chunk.requirement_ids[0] is the exact ID from the document (e.g. FR-001)
    # If multiple IDs exist (cross-references), they are stored in all_ids
    # but the primary ID is always [0]
    for sentence in sentences:
      try:
        # RP3: testing type assignment
        if review_points.get("rp3", True):
            testing_type = assign_testing_type(sentence, chunk.module)
        else:
            testing_type = "verification"

        env    = assign_environment(testing_type)
        prefix = prefix_map[testing_type]
        subject = extract_subject(sentence)
        action  = extract_action(sentence)

        # RP4: remarks — include notes_context from document (enums, sub-reqs, notes)
        notes_ctx = getattr(chunk, "notes_context", "")
        # Determine input source: ICD if no explicit values in SRS (Req 4)
        input_source = "ICD" if not any(
            kw in sentence.lower() for kw in ["is true", "is false", "= true", "= false",
                                               "value is", "values are", "range", "between"]
        ) else "SRS"

        for scenario_type in scenario_types:
            tc_counters[prefix] += 1
            tc_id = f"TC_{prefix}_{tc_counters[prefix]:03d}"
            sc_id = f"SC_{sc_counter:03d}"

            priority    = assign_priority(chunk.requirement_type, scenario_type, testing_type)
            methodology = assign_methodology(sentence, scenario_type)

            # Escape curly braces in action/subject so .format() does not
            # misinterpret document text like {GPS} or {value} as placeholders
            action_fmt  = action.replace("{", "{{").replace("}", "}}") if action else "perform operation"
            subject_fmt = subject.replace("{", "{{").replace("}", "}}") if subject else "the system"

            # Build steps
            steps = [
                s.format(
                    subject=subject_fmt,
                    action=action_fmt,
                    edge_input="concurrent request / session timeout / state transition",
                    robustness_input="SQL injection / XSS payload / oversized input",
                )
                for s in STEP_TEMPLATES[scenario_type]
            ]

            # Build inputs
            inputs = [
                t.format(subject=subject_fmt)
                for t in INPUT_TEMPLATES[scenario_type]
            ]

            # Build preconditions with pre-set input info (Req 9)
            preconditions = [
                t.format(module=chunk.module, subject=subject_fmt, env=env)
                for t in PRECONDITION_TEMPLATES[scenario_type]
            ]
            # Req 9: indicate pre-set input values from requirement + output generation logic
            if scenario_type == "normal":
                # Check for predefined values in the requirement text
                preset_matches = re.findall(
                    r'(?:is|=|equals?|set\s+to)\s+(True|False|Active|Inactive|\d+(?:\.\d+)?)',
                    sentence, re.IGNORECASE
                )
                if preset_matches:
                    preset_str = ", ".join(preset_matches)
                    preconditions.append(
                        f"Pre-set input values from requirement: {preset_str}"
                    )
                    preconditions.append(
                        f"Output is generated when ALL specified input conditions are met; "
                        f"changes in any input will directly influence the output state"
                    )

            # Build expected outcome
            expected = EXPECTED_OUTCOME_TEMPLATES[scenario_type].format(action=action_fmt)

            # ── Sequence output transitions ──────────────────────────────────
            # Embed an explicit output signal value so the Excel output signal
            # column shows the logically correct value for each scenario:
            #   normal / boundary → True  (positive path, conditions met)
            #   edge / robustness → False (negative/fault path)
            #
            # Detection order (first match wins):
            #  1. "shall set <Signal> to True/Enabled/Active/1"   (positive form)
            #  2. "shall set <Signal> to False/Disabled/Inactive/0" (negative form → invert)
            #  3. "<Signal> shall be set to True/..."              (passive form)
            #  4. "<Signal> = True/..."                            (assignment form)
            #  5. "<Signal> is True/..."                           (state form)
            _BOOL_VALS_TRUE  = r'(True|Enabled|Active|1)'
            _BOOL_VALS_FALSE = r'(False|Disabled|Inactive|0)'
            _BOOL_VALS_ANY   = r'(True|False|Enabled|Disabled|Active|Inactive|1|0)'

            _sig_name  = None
            _true_val  = None   # the "positive" value for this signal
            _false_val = None   # the "negative" value for this signal

            # Pattern 1 — positive: "shall set <Signal> to True/Enabled/Active/1"
            _QUOTE_OPT = '[\"\']?'
            _m = re.search(
                r"(?:shall|must|will)\s+set\s+(?:the\s+)?([\w\s]{3,60}?)\s+to\s+"
                + _QUOTE_OPT + _BOOL_VALS_TRUE + _QUOTE_OPT,
                sentence, re.IGNORECASE
            )
            if _m:
                _sig_name = _m.group(1).strip().rstrip("'")
                _true_val = _m.group(2)

            # Pattern 2 — negative form: "shall set <Signal> to False/Disabled/..."
            # This means the signal's TRUE value is the opposite (for normal scenario)
            if not _sig_name:
                _m = re.search(
                    r"(?:shall|must|will)\s+set\s+(?:the\s+)?([\w\s]{3,60}?)\s+to\s+"
                    + _QUOTE_OPT + _BOOL_VALS_FALSE + _QUOTE_OPT,
                    sentence, re.IGNORECASE
                )
                if _m:
                    _sig_name = _m.group(1).strip().rstrip("'")
                    _negative = _m.group(2)   # e.g. "False"
                    # The "positive" (normal/boundary) value is the inverse
                    _true_val = (
                        "True"   if _negative.lower() in ("false", "0")      else
                        "Enabled"  if _negative.lower() == "disabled"          else
                        "Active"   if _negative.lower() == "inactive"          else
                        "True"
                    )
                    _false_val = _negative    # already the false value

            # Pattern 3 — passive: "<Signal> shall be set to <BoolVal>"
            if not _sig_name:
                _m = re.search(
                    r"([\w\s]{3,50}?)\s+(?:shall|must|will|should)\s+be\s+set\s+to\s+"
                    + _QUOTE_OPT + _BOOL_VALS_ANY + _QUOTE_OPT,
                    sentence, re.IGNORECASE
                )
                if _m:
                    _cand = _m.group(1).strip().rstrip("'")
                    _val  = _m.group(2)
                    # Only use if candidate looks like a signal name (≤8 words)
                    if 1 <= len(_cand.split()) <= 8:
                        _sig_name = _cand
                        _true_val = (
                            _val if _val.lower() in ("true","enabled","active","1")
                            else (
                                "True"    if _val.lower() in ("false","0")      else
                                "Enabled" if _val.lower() == "disabled"          else
                                "Active"  if _val.lower() == "inactive"          else
                                "True"
                            )
                        )

            # Pattern 4 — assignment: "<Signal> = <BoolVal>"
            if not _sig_name:
                _m = re.search(
                    r"([A-Z][\w\s]{2,50}?)\s*=\s*" + _BOOL_VALS_ANY + r"\b",
                    sentence
                )
                if _m:
                    _cand = _m.group(1).strip()
                    _val  = _m.group(2)
                    if 1 <= len(_cand.split()) <= 8:
                        _sig_name = _cand
                        _true_val = (
                            _val if _val.lower() in ("true","enabled","active","1")
                            else (
                                "True"    if _val.lower() in ("false","0")      else
                                "Enabled" if _val.lower() == "disabled"          else
                                "Active"  if _val.lower() == "inactive"          else
                                "True"
                            )
                        )

            # Pattern 5 — state: "<Signal> is <BoolVal>"
            if not _sig_name:
                _m = re.search(
                    r"([A-Z][\w\s]{2,50}?)\s+is\s+"
                    + _QUOTE_OPT + _BOOL_VALS_ANY + _QUOTE_OPT + r"\b",
                    sentence
                )
                if _m:
                    _cand = _m.group(1).strip()
                    _val  = _m.group(2)
                    if 1 <= len(_cand.split()) <= 8:
                        _sig_name = _cand
                        _true_val = (
                            _val if _val.lower() in ("true","enabled","active","1")
                            else (
                                "True"    if _val.lower() in ("false","0")      else
                                "Enabled" if _val.lower() == "disabled"          else
                                "Active"  if _val.lower() == "inactive"          else
                                "True"
                            )
                        )

            if _sig_name and _true_val:
                if _false_val is None:
                    _false_val = (
                        "False"    if _true_val.lower() in ("true","1")        else
                        "Disabled" if _true_val.lower() == "enabled"           else
                        "Inactive" if _true_val.lower() == "active"            else
                        "False"
                    )
                # Apply the logical value for this scenario type
                _seq_value = (
                    _true_val  if scenario_type in ("normal", "boundary") else
                    _false_val   # edge / robustness → output is False / negative
                )
                # Prepend "SignalName = Value." so _get_signal_value() in
                # output_generator.py picks it up for the Excel output column.
                expected = f"{_sig_name} = {_seq_value}. " + expected

            # Generate remarks per scenario (Req 8 — scenario-type-specific)
            remarks = (
                generate_remarks(sentence, primary_req_id, notes_ctx, scenario_type, input_source)
                if review_points.get("rp4", True)
                else f"• Scenario ({scenario_type.upper()}): Verify before execution."
            )

            # Dependency resolution:
            # - For scenario types: boundary/edge/robustness depend on normal TC
            # - For sub-requirements: normal TC depends on parent's first normal TC
            deps = resolve_dependencies(scenario_type, results, primary_req_id)
            if scenario_type == "normal" and chunk.is_sub_req and chunk.parent_id:
                parent_tc = req_to_first_tc.get(chunk.parent_id)
                if parent_tc:
                    deps = parent_tc   # sub-req normal TC depends on parent normal TC

            results.append(TestCase(
                traceability_req_id  = primary_req_id,
                test_case_id         = tc_id,
                scenario_id          = sc_id,
                priority             = priority,
                objective            = f"[{scenario_type.upper()}] Verify {subject} {action}",
                preconditions        = preconditions,
                test_steps           = steps,
                inputs               = inputs,
                design_methodology   = methodology,
                dependent_test_cases = deps,
                expected_outcome     = expected,
                test_environment     = env,
                remarks              = remarks,
                module               = chunk.module,
                requirement_type     = chunk.requirement_type,
                scenario_type        = scenario_type,
                testing_type         = testing_type,
            ))

        # Track first TC generated for this requirement (used for sub-req dependencies)
        if primary_req_id not in req_to_first_tc and results:
            # Find the first normal TC for this req
            for tc in results:
                if tc.traceability_req_id == primary_req_id and tc.scenario_type == "normal":
                    req_to_first_tc[primary_req_id] = tc.test_case_id
                    break

      except Exception as _sentence_err:
          logger.warning(f"Skipping sentence due to error: {_sentence_err} — sentence: {sentence[:60]}")

      sc_counter += 1

    return results, sc_counter


# ─── DEDUPLICATION ────────────────────────────────────────────────────────────

def _resequence(test_cases: List[TestCase]) -> List[TestCase]:
    """
    Always runs after generation (even when rp5 deduplication is off).

    Rules:
      1. ONE TC_ID per requirement — increments only when req ID changes.
      2. SC resets to SC_001 for each new requirement group.
      3. Depands_On:
           SC_001 (baseline) -> "None"
           SC_002+           -> TC_ID_SC-001  (hyphen, references baseline)
    """
    prefix_counters: Dict[str, int] = {}
    req_to_new_tcid: Dict[str, str] = {}

    for tc in test_cases:
        req_id = tc.traceability_req_id
        if req_id not in req_to_new_tcid:
            m = re.match(r'^(TC_[A-Z]+_)', tc.test_case_id)
            prefix = m.group(1) if m else "TC_UT_"
            prefix_counters[prefix] = prefix_counters.get(prefix, 0) + 1
            req_to_new_tcid[req_id] = f"{prefix}{prefix_counters[prefix]:03d}"

    sc_counters_per_req: Dict[str, int] = {}
    resequenced: List[TestCase] = []

    for tc in test_cases:
        req_id    = tc.traceability_req_id
        new_tc_id = req_to_new_tcid[req_id]
        sc_counters_per_req[req_id] = sc_counters_per_req.get(req_id, 0) + 1
        new_sc_id = f"SC_{sc_counters_per_req[req_id]:03d}"
        resequenced.append(tc.model_copy(update={
            "test_case_id": new_tc_id,
            "scenario_id":  new_sc_id,
        }))

    final: List[TestCase] = []
    seen_req: set = set()

    for tc in resequenced:
        req_id = tc.traceability_req_id
        if req_id not in seen_req:
            seen_req.add(req_id)
            final.append(tc.model_copy(update={"dependent_test_cases": "None"}))
        else:
            dep = f"{tc.test_case_id}_SC-001"
            final.append(tc.model_copy(update={"dependent_test_cases": dep}))

    return final


def deduplicate(test_cases: List[TestCase]) -> Tuple[List[TestCase], int]:
    """
    Removes genuinely duplicate test cases.

    KEY RULE: Test cases for the SAME requirement but DIFFERENT scenario types
    (normal / boundary / edge / robustness) are NEVER duplicates — they are
    intentionally distinct scenarios and must ALL be kept.

    A true duplicate is: same requirement_id AND same scenario_type AND
    near-identical objective (ratio > DEDUP_THRESHOLD).

    Also protected from deduplication:
    - Decision Table Testing TCs
    - Condition Coverage Testing TCs
    """
    PROTECTED_METHODOLOGIES = {"Decision Table Testing", "Condition Coverage Testing", "MC/DC Testing"}

    # Build a key: (traceability_req_id, scenario_type) → list of seen objectives
    # Only compare within the same req+scenario_type bucket
    seen_by_bucket: Dict[str, List[str]] = {}

    kept, removed = [], 0
    for tc in test_cases:
        # Always keep protected methodologies
        if tc.design_methodology in PROTECTED_METHODOLOGIES:
            kept.append(tc)
            continue

        # Bucket key: same requirement + same scenario_type only
        bucket = f"{tc.traceability_req_id}::{tc.scenario_type}"
        bucket_seen = seen_by_bucket.setdefault(bucket, [])

        is_dup = any(
            SequenceMatcher(None, tc.objective.lower(), s.lower()).ratio() > DEDUP_THRESHOLD
            for s in bucket_seen
        )
        if is_dup:
            removed += 1
            logger.debug(f"Duplicate removed: {tc.test_case_id} — {tc.objective[:60]}")
        else:
            bucket_seen.append(tc.objective)
            kept.append(tc)

    logger.info(f"Deduplication: kept {len(kept)}, removed {removed}")

    return kept, removed


# ─── MAIN ENTRY POINT ─────────────────────────────────────────────────────────

# ─── PARENT + CHILD ANALYSIS ENGINE ──────────────────────────────────────────

def _clean_sub_content(chunk: DocumentChunk) -> str:
    """Returns the sub-requirement content without the [Parent...] prefix."""
    c = chunk.content
    if "[Sub-Requirement" in c:
        parts = c.split("]: ", 1)
        return parts[1].strip() if len(parts) > 1 else c
    return c


def _should_merge(parent_chunk: DocumentChunk, child_chunks: List[DocumentChunk]) -> bool:
    """
    Decides whether parent + children should be MERGED into single test cases.

    MERGE when ALL conditions met:
    ✓ 2 or 3 children (≤3 — more becomes unwieldy in one TC)
    ✓ All children in the same module as parent
    ✓ Each child is a simple, short refinement (≤ 30 words)
    ✓ Children share the same subject as parent (they are parts of ONE behaviour)

    SEPARATE when ANY condition fails:
    ✗ 4 or more children
    ✗ A child belongs to a different module
    ✗ Any child is long / introduces distinct new behaviour (> 30 words)
    """
    if len(child_chunks) < 2 or len(child_chunks) > 3:
        return False
    if any(c.module != parent_chunk.module for c in child_chunks):
        return False
    parent_subject = extract_subject(parent_chunk.content).lower()
    for child in child_chunks:
        clean = _clean_sub_content(child)
        if len(clean.split()) > 30:
            return False
        # Children that introduce completely new subjects → separate
        child_subject = extract_subject(clean).lower()
        if child_subject and parent_subject and child_subject not in parent_subject and parent_subject not in child_subject:
            # Allow if subjects are very short tokens (likely same entity, different wording)
            if len(child_subject.split()) > 2 and len(parent_subject.split()) > 2:
                return False
    return True


def _generate_merged_tcs(
    parent_chunk: DocumentChunk,
    child_chunks: List[DocumentChunk],
    tc_counters: Dict[str, int],
    sc_counter: int,
    review_points: dict,
) -> Tuple[List[TestCase], int]:
    """
    Generates MERGED test cases: parent + all children covered in one TC per scenario.
    Used when children are simple refinements of the parent.

    The traceability_req_id shows ALL IDs: "HLR-NAV-001 [+.1,.2]"
    Steps explicitly verify each sub-requirement within the same TC.
    """
    results      = []
    prefix_map   = {"validation": "VD", "integration": "IT", "verification": "UT"}
    parent_id    = parent_chunk.requirement_ids[0]
    child_ids    = [c.requirement_ids[0] for c in child_chunks]
    combined_id  = f"{parent_id} [incl. {', '.join(child_ids)}]"

    parent_content = parent_chunk.content
    subject = extract_subject(parent_content)
    action  = extract_action(parent_content)

    testing_type = assign_testing_type(parent_content, parent_chunk.module)
    prefix       = prefix_map[testing_type]
    env          = assign_environment(testing_type)

    scenario_types = (
        ("normal", "boundary", "edge", "robustness")
        if review_points.get("rp2", True)
        else ("normal",)
    )

    for scenario_type in scenario_types:
        tc_counters[prefix] += 1
        tc_id = f"TC_{prefix}_{tc_counters[prefix]:03d}"
        sc_id = f"SC_{sc_counter:03d}"

        # Escape curly braces so .format() does not misread document tokens
        action_fmt  = action.replace("{", "{{").replace("}", "}}") if action else "perform operation"
        subject_fmt = subject.replace("{", "{{").replace("}", "}}") if subject else "the system"

        # Base steps for this scenario
        base_steps = [
            s.format(
                subject=subject_fmt, action=action_fmt,
                edge_input="concurrent/timeout/state-transition",
                robustness_input="SQL injection / XSS / malformed input",
            )
            for s in STEP_TEMPLATES[scenario_type]
        ]

        # Append explicit sub-requirement verification steps
        sub_steps = []
        for i, (child_id, child) in enumerate(zip(child_ids, child_chunks), start=1):
            child_action = extract_action(_clean_sub_content(child))
            sub_steps.append(
                f"{len(base_steps)+i}. Verify sub-req {child_id}: {child_action}"
            )
        sub_steps.append(
            f"{len(base_steps)+len(sub_steps)+1}. Confirm all sub-requirements "
            f"collectively satisfy parent {parent_id}"
        )

        # Combined inputs cover parent + all children
        inputs = [t.format(subject=subject_fmt) for t in INPUT_TEMPLATES[scenario_type]]
        inputs.append(f"Sub-requirements scope: {', '.join(child_ids)}")

        remarks_text = (
            f"• MERGED TC — covers {combined_id} as a single unit.\n"
            f"• Children are simple refinements of the parent; merging reduces redundancy.\n"
        )
        if review_points.get("rp4", True):
            remarks_text += generate_remarks(parent_content, parent_id,
                                             scenario_type=scenario_type)

        # Build expected outcome with output signal transition for merged TC
        _merged_base_exp = (
            EXPECTED_OUTCOME_TEMPLATES[scenario_type].format(action=action_fmt)
            + f" All sub-requirements ({', '.join(child_ids)}) "
            f"are satisfied within this single test."
        )
        # Detect output signal from parent requirement using the same multi-pattern
        # approach as the per-sentence path (positive, negative, passive, assign, state)
        _mQUOTE = '["\'\u2018\u2019\u201c\u201d]?'
        _mBOOL_T = r'(True|Enabled|Active|1)'
        _mBOOL_F = r'(False|Disabled|Inactive|0)'
        _mBOOL_A = r'(True|False|Enabled|Disabled|Active|Inactive|1|0)'
        _msig = None; _mtv = None; _mfv = None
        for _mpat, _mpositive in [
            (r"(?:shall|must|will)\s+set\s+(?:the\s+)?([\w\s]{3,60}?)\s+to\s+" + _mQUOTE + _mBOOL_T + _mQUOTE, True),
            (r"(?:shall|must|will)\s+set\s+(?:the\s+)?([\w\s]{3,60}?)\s+to\s+" + _mQUOTE + _mBOOL_F + _mQUOTE, False),
            (r"([\w\s]{3,50}?)\s+(?:shall|must|will|should)\s+be\s+set\s+to\s+" + _mQUOTE + _mBOOL_A + _mQUOTE, None),
            (r"([A-Z][\w\s]{2,50}?)\s*=\s*" + _mBOOL_A + r"\b", None),
            (r"([A-Z][\w\s]{2,50}?)\s+is\s+" + _mQUOTE + _mBOOL_A + _mQUOTE + r"\b", None),
        ]:
            _mm = re.search(_mpat, parent_content, re.IGNORECASE)
            if _mm:
                _mcand = _mm.group(1).strip().rstrip("'")
                _mval  = _mm.group(2)
                if 1 <= len(_mcand.split()) <= 8:
                    _msig = _mcand
                    if _mpositive is True:
                        _mtv = _mval
                    elif _mpositive is False:
                        _mfv = _mval
                        _mtv = ("True" if _mval.lower() in ("false","0") else
                                "Enabled" if _mval.lower() == "disabled" else
                                "Active"  if _mval.lower() == "inactive" else "True")
                    else:
                        if _mval.lower() in ("true","enabled","active","1"):
                            _mtv = _mval
                        else:
                            _mfv = _mval
                            _mtv = ("True" if _mval.lower() in ("false","0") else
                                    "Enabled" if _mval.lower() == "disabled" else
                                    "Active"  if _mval.lower() == "inactive" else "True")
                    break
        if _msig and _mtv:
            if _mfv is None:
                _mfv = ("False"    if _mtv.lower() in ("true","1")   else
                        "Disabled" if _mtv.lower() == "enabled"       else
                        "Inactive" if _mtv.lower() == "active"        else "False")
            _msv = _mtv if scenario_type in ("normal", "boundary") else _mfv
            _merged_expected = f"{_msig} = {_msv}. " + _merged_base_exp
        else:
            _merged_expected = _merged_base_exp

        results.append(TestCase(
            traceability_req_id  = combined_id,
            test_case_id         = tc_id,
            scenario_id          = sc_id,
            priority             = assign_priority(parent_chunk.requirement_type, scenario_type, testing_type),
            objective            = (
                f"[{scenario_type.upper()}] Verify {subject} {action} "
                f"satisfying {parent_id} and sub-requirements "
                f"{', '.join(child_ids)}"
            ),
            preconditions        = [
                t.format(module=parent_chunk.module, subject=subject_fmt, env=env)
                for t in PRECONDITION_TEMPLATES[scenario_type]
            ],
            test_steps           = base_steps + sub_steps,
            inputs               = inputs,
            design_methodology   = assign_methodology(parent_content, scenario_type),
            dependent_test_cases = "None",
            expected_outcome     = _merged_expected,
            test_environment     = env,
            remarks              = remarks_text,
            module               = parent_chunk.module,
            requirement_type     = parent_chunk.requirement_type,
            scenario_type        = scenario_type,
            testing_type         = testing_type,
        ))

    sc_counter += 1
    logger.info(
        f"MERGED: {parent_id} + {child_ids} → "
        f"{len(results)} TCs (children are simple refinements)"
    )
    return results, sc_counter


def _generate_separated_tcs(
    parent_chunk: DocumentChunk,
    child_chunks: List[DocumentChunk],
    tc_counters: Dict[str, int],
    sc_counter: int,
    review_points: dict,
    req_to_first_tc: Dict[str, str],
) -> Tuple[List[TestCase], int]:
    """
    Generates SEPARATE test cases for parent and each child individually,
    plus one integration TC that verifies them working together.
    Used when children introduce distinct behaviours.
    """
    all_results  = []
    parent_id    = parent_chunk.requirement_ids[0]
    prefix_map   = {"validation": "VD", "integration": "IT", "verification": "UT"}

    # ── Generate parent TCs (without child context) ───────────────────────────
    parent_tcs, sc_counter = generate_for_chunk(
        parent_chunk, tc_counters, sc_counter, review_points, req_to_first_tc
    )
    all_results.extend(parent_tcs)
    logger.info(f"SEPARATE parent {parent_id}: {len(parent_tcs)} TCs")

    # ── Generate individual TCs for each child ────────────────────────────────
    for child in child_chunks:
        child_id   = child.requirement_ids[0]
        child_tcs, sc_counter = generate_for_chunk(
            child, tc_counters, sc_counter, review_points, req_to_first_tc
        )
        all_results.extend(child_tcs)
        logger.info(f"SEPARATE child  {child_id}: {len(child_tcs)} TCs")

    # ── Integration TC: parent + all children together ────────────────────────
    tc_counters["IT"] += 1
    int_tc_id = f"TC_IT_{tc_counters['IT']:03d}"
    child_ids = [c.requirement_ids[0] for c in child_chunks]

    # Dependencies: first normal TC of every child
    child_first_tcs = [req_to_first_tc[cid] for cid in child_ids if cid in req_to_first_tc]
    parent_first_tc = req_to_first_tc.get(parent_id, "None")

    int_steps = [
        f"1. Confirm all individual TCs for {parent_id} have passed",
    ]
    for i, child_id in enumerate(child_ids, start=2):
        int_steps.append(f"{i}. Confirm all individual TCs for sub-req {child_id} have passed")
    int_steps += [
        f"{len(child_ids)+2}. Execute a combined end-to-end flow covering the full scope of {parent_id}",
        f"{len(child_ids)+3}. Verify there are no gaps, conflicts, or overlaps between sub-requirements",
        f"{len(child_ids)+4}. Confirm sub-requirements collectively and completely satisfy {parent_id}",
    ]

    deps = ", ".join([parent_first_tc] + child_first_tcs) if parent_first_tc != "None" or child_first_tcs else "None"

    all_results.append(TestCase(
        traceability_req_id  = parent_id,
        test_case_id         = int_tc_id,
        scenario_id          = f"SC_{sc_counter:03d}",
        priority             = "P1",
        objective            = (
            f"Verify that {parent_id} and its sub-requirements "
            f"({', '.join(child_ids)}) work correctly together as a complete unit"
        ),
        preconditions        = [
            f"All individual TCs for {parent_id} have passed",
            f"All individual TCs for sub-requirements ({', '.join(child_ids)}) have passed",
            f"System is in a clean state in the {parent_chunk.module} module",
        ],
        test_steps           = int_steps,
        inputs               = [
            "Combined inputs exercising the full scope of the parent requirement",
            "Valid data satisfying all sub-requirement constraints simultaneously",
        ],
        design_methodology   = "Integration Testing",
        dependent_test_cases = deps,
        expected_outcome     = (
            f"Sub-requirements {', '.join(child_ids)} collectively satisfy "
            f"{parent_id} with no gaps or conflicts. "
            f"The system behaves correctly as a complete integrated unit."
        ),
        test_environment     = "QA",
        remarks              = (
            f"INTEGRATION TC — generated because {parent_id} has "
            f"{len(child_chunks)} children with distinct behaviours. "
            f"Run AFTER all individual TCs have passed. "
            f"Validates completeness and inter-operability of sub-requirements."
        ),
        module               = parent_chunk.module,
        requirement_type     = parent_chunk.requirement_type,
        scenario_type        = "normal",
        testing_type         = "integration",
    ))
    sc_counter += 1
    logger.info(f"SEPARATE integration TC {int_tc_id} for {parent_id} + {child_ids}")
    return all_results, sc_counter


# ─── MAIN ENTRY POINT ─────────────────────────────────────────────────────────

def generate_all(
    chunks: List[DocumentChunk],
    review_points: dict,
) -> Tuple[List[TestCase], int]:
    """
    Generates test cases for all chunks with intelligent parent-child handling.

    For EVERY parent requirement, children are analysed IN-LINE (not after):
      → _should_merge() decides: simple refinements → MERGE, distinct behaviours → SEPARATE
      → MERGE  : one set of TCs per scenario type covering parent + all children together
      → SEPARATE: individual TCs for parent + each child + one integration TC

    Standalone requirements (no parent, no children): standard generation.
    Sub-requirements whose parent was already processed: SKIPPED (handled inline).
    """
    tc_counters     = {"VD": 0, "IT": 0, "UT": 0}
    sc_counter      = 1
    all_test_cases  : List[TestCase] = []
    req_to_first_tc : Dict[str, str] = {}
    processed       : set            = set()   # tracks req_ids already handled

    id_to_chunk = {
        c.requirement_ids[0]: c
        for c in chunks if c.requirement_ids
    }

    for chunk in chunks:
        if not chunk.requirement_ids:
            continue
        req_id = chunk.requirement_ids[0]
        if req_id in processed:
            continue  # already handled inline with its parent

        # ── Case 1: Parent with children ──────────────────────────────────────
        if chunk.has_children:
            child_chunks = [
                id_to_chunk[cid]
                for cid in chunk.child_ids
                if cid in id_to_chunk
            ]

            if _should_merge(chunk, child_chunks):
                # ── MERGE: children are simple refinements ──────────────────
                tcs, sc_counter = _generate_merged_tcs(
                    chunk, child_chunks, tc_counters, sc_counter, review_points
                )
            else:
                # ── SEPARATE: children have distinct behaviours ─────────────
                tcs, sc_counter = _generate_separated_tcs(
                    chunk, child_chunks, tc_counters, sc_counter,
                    review_points, req_to_first_tc
                )

            all_test_cases.extend(tcs)
            processed.add(req_id)
            for child in child_chunks:
                processed.add(child.requirement_ids[0])

        # ── Case 2: Orphan sub-requirement (parent not in document) ──────────
        elif chunk.is_sub_req and chunk.parent_id not in id_to_chunk:
            tcs, sc_counter = generate_for_chunk(
                chunk, tc_counters, sc_counter, review_points, req_to_first_tc
            )
            all_test_cases.extend(tcs)
            processed.add(req_id)

        # ── Case 3: Standalone requirement (no parent, no children) ──────────
        elif not chunk.is_sub_req:
            tcs, sc_counter = generate_for_chunk(
                chunk, tc_counters, sc_counter, review_points, req_to_first_tc
            )
            all_test_cases.extend(tcs)
            processed.add(req_id)

    if review_points.get("rp5", True):
        all_test_cases, removed = deduplicate(all_test_cases)
    else:
        removed = 0

    # Always resequence: shared TC_ID per req, SC resets per req, Depands_On set.
    # Runs regardless of rp5 so GUI and Excel always show the same TC_IDs.
    all_test_cases = _resequence(all_test_cases)

    return all_test_cases, removed