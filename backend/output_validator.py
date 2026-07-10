"""
output_validator.py
-------------------
Validates AI-generated test cases before they are stored in mcp_results_store.

Three validation layers:
  1. Schema      — all 16 required fields present with correct types/Literals
  2. Content     — fields are meaningful (not empty, not placeholder text)
  3. Traceability — traceability_req_id matches a queued requirement ID

Returns a ValidationReport with:
  - passed / failed counts
  - per-test-case issues list
  - fixed test cases (auto-corrected where possible)
  - unfixable test cases (dropped with reason logged)
"""

from __future__ import annotations
import re
import logging
from dataclasses import dataclass, field
from typing import List, Dict, Any, Set, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

REQUIRED_FIELDS = [
    "traceability_req_id", "test_case_id", "scenario_id",
    "priority", "objective", "preconditions", "test_steps",
    "inputs", "design_methodology", "dependent_test_cases",
    "expected_outcome", "test_environment", "remarks",
    "module", "requirement_type", "scenario_type", "testing_type",
]

VALID_PRIORITY     = {"P1", "P2", "P3"}
VALID_ENVIRONMENT  = {"Dev", "QA", "UAT", "Prod"}
VALID_REQ_TYPE     = {"functional", "non-functional"}
VALID_SCENARIO     = {"normal", "boundary", "edge", "robustness", "transition"}
VALID_TESTING      = {"verification", "validation", "integration"}

# Placeholder strings Claude sometimes writes when it doesn't know a value
PLACEHOLDER_PATTERNS = re.compile(
    r"^(n/?a|none|tbd|tbc|not applicable|not specified|unknown|"
    r"placeholder|fill in|to be determined|todo|--|---|N/A)$",
    re.IGNORECASE,
)

# Req 4: an Input Value should never be a generic, unfilled hint like
# "<invalid/out-of-range value>" or the bare phrase "out-of-range value" —
# it should be the actual invalid/garbage value used for the test.
GENERIC_INPUT_VALUE_PATTERNS = re.compile(
    r"<[^>]*>|"
    r"^out[-\s]?of[-\s]?range(\s+value)?$|"
    r"^invalid(/out-of-range)?(\s+value)?$|"
    r"^(exact\s+)?threshold(\s+value)?$",
    re.IGNORECASE,
)

EMPTY_LIKE = {"", "-", "--", "none", "n/a", "tbd", "null", "nil"}


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class TestCaseIssue:
    test_case_id: str
    req_id: str
    severity: str          # "error" | "warning" | "fixed"
    field: str
    message: str


@dataclass
class ValidationReport:
    total_input: int = 0
    passed: int = 0
    auto_fixed: int = 0
    dropped: int = 0
    issues: List[TestCaseIssue] = field(default_factory=list)
    valid_test_cases: List[Dict[str, Any]] = field(default_factory=list)
    dropped_test_cases: List[Dict[str, Any]] = field(default_factory=list)

    def summary(self) -> Dict[str, Any]:
        return {
            "total_input":   self.total_input,
            "passed":        self.passed,
            "auto_fixed":    self.auto_fixed,
            "dropped":       self.dropped,
            "total_saved":   self.passed + self.auto_fixed,
            "error_count":   sum(1 for i in self.issues if i.severity == "error"),
            "warning_count": sum(1 for i in self.issues if i.severity == "warning"),
            "fixed_count":   sum(1 for i in self.issues if i.severity == "fixed"),
            "issue_details": [
                {
                    "test_case_id": i.test_case_id,
                    "req_id":       i.req_id,
                    "severity":     i.severity,
                    "field":        i.field,
                    "message":      i.message,
                }
                for i in self.issues
            ],
        }


# ── Core validator ────────────────────────────────────────────────────────────

def validate_test_cases(
    raw_test_cases: List[Dict[str, Any]],
    valid_req_ids: Optional[Set[str]] = None,
) -> ValidationReport:
    """
    Validate and auto-fix a list of raw test case dicts from Claude.

    Args:
        raw_test_cases:  List of dicts as returned by save_enhanced_test_cases
        valid_req_ids:   Set of requirement IDs from the queued SRS session.
                         If provided, traceability is checked against this set.

    Returns:
        ValidationReport with valid_test_cases ready to store.
    """
    report = ValidationReport(total_input=len(raw_test_cases))

    for raw in raw_test_cases:
        tc_id  = str(raw.get("test_case_id", "?"))
        req_id = str(raw.get("traceability_req_id", "?"))
        issues: List[TestCaseIssue] = []
        drop = False
        tc = dict(raw)  # work on a copy

        # ── LAYER 1: Schema — required fields ─────────────────────────────────
        for f in REQUIRED_FIELDS:
            if f not in tc or tc[f] is None:
                # Auto-fix with safe defaults
                default = _default_for_field(f)
                tc[f] = default
                issues.append(TestCaseIssue(
                    tc_id, req_id, "fixed", f,
                    f"Missing field '{f}' — filled with default: {default!r}"
                ))

        # ── LAYER 2: Literal values ────────────────────────────────────────────
        tc, lit_issues = _fix_literals(tc, tc_id, req_id)
        issues.extend(lit_issues)

        # ── LAYER 3: Content — meaningful values ───────────────────────────────
        content_issues = _check_content(tc, tc_id, req_id)
        issues.extend(content_issues)
        # Drop only if BOTH objective AND expected_outcome are empty/placeholder
        obj_empty = _is_empty(tc.get("objective", ""))
        exp_empty = _is_empty(tc.get("expected_outcome", ""))
        if obj_empty and exp_empty:
            issues.append(TestCaseIssue(
                tc_id, req_id, "error", "objective+expected_outcome",
                "Both objective and expected_outcome are empty — test case dropped"
            ))
            drop = True

        # ── LAYER 4: Traceability ──────────────────────────────────────────────
        if valid_req_ids and tc.get("traceability_req_id"):
            rid = tc["traceability_req_id"]
            if rid not in valid_req_ids:
                # Try fuzzy match — maybe a minor suffix/case difference
                match = _fuzzy_req_match(rid, valid_req_ids)
                if match:
                    issues.append(TestCaseIssue(
                        tc_id, req_id, "fixed", "traceability_req_id",
                        f"Req ID {rid!r} not in queue — corrected to {match!r}"
                    ))
                    tc["traceability_req_id"] = match
                else:
                    issues.append(TestCaseIssue(
                        tc_id, req_id, "warning", "traceability_req_id",
                        f"Req ID {rid!r} not found in queued requirements — kept as-is"
                    ))

        # ── Collect result ─────────────────────────────────────────────────────
        report.issues.extend(issues)

        if drop:
            report.dropped += 1
            report.dropped_test_cases.append(tc)
        else:
            fixed_count = sum(1 for i in issues if i.severity == "fixed")
            if fixed_count > 0:
                report.auto_fixed += 1
            else:
                report.passed += 1
            report.valid_test_cases.append(tc)

    # Log summary
    s = report.summary()
    logger.info(
        f"[VALIDATION] {s['total_input']} in → "
        f"{s['total_saved']} saved ({s['passed']} clean, "
        f"{s['auto_fixed']} fixed, {s['dropped']} dropped) | "
        f"errors={s['error_count']} warnings={s['warning_count']}"
    )

    return report


# ── Helpers ───────────────────────────────────────────────────────────────────

def _default_for_field(f: str) -> Any:
    defaults = {
        "traceability_req_id": "UNKNOWN",
        "test_case_id":        "TC_AUTO",
        "scenario_id":         "SC_AUTO",
        "priority":            "P2",
        "objective":           "",
        "preconditions":       [],
        "test_steps":          [],
        "inputs":              [],
        "design_methodology":  "Equivalence Partitioning",
        "dependent_test_cases":"None",
        "expected_outcome":    "",
        "test_environment":    "Dev",
        "remarks":             "",
        "module":              "General",
        "requirement_type":    "functional",
        "scenario_type":       "normal",
        "testing_type":        "verification",
    }
    return defaults.get(f, "")


def _fix_literals(
    tc: dict, tc_id: str, req_id: str
) -> Tuple[dict, List[TestCaseIssue]]:
    issues = []

    # priority
    p = str(tc.get("priority", "P1")).upper().strip()
    if p not in VALID_PRIORITY:
        fixed = "P1" if any(x in p for x in ("HIGH","CRIT","MUST","1")) else \
                "P3" if any(x in p for x in ("LOW","NICE","3")) else "P2"
        issues.append(TestCaseIssue(tc_id, req_id, "fixed", "priority",
                                    f"{p!r} → {fixed!r}"))
        tc["priority"] = fixed

    # test_environment
    env = str(tc.get("test_environment", "Dev")).strip()
    if env not in VALID_ENVIRONMENT:
        env_l = env.lower()
        fixed = "Prod" if "prod" in env_l else \
                "UAT"  if "uat" in env_l or "accept" in env_l else \
                "QA"   if "qa" in env_l or "test" in env_l else "Dev"
        issues.append(TestCaseIssue(tc_id, req_id, "fixed", "test_environment",
                                    f"{env!r} → {fixed!r}"))
        tc["test_environment"] = fixed

    # requirement_type
    rt = str(tc.get("requirement_type", "functional")).lower().strip()
    if rt not in VALID_REQ_TYPE:
        fixed = "non-functional" if "non" in rt or "nonfunc" in rt else "functional"
        issues.append(TestCaseIssue(tc_id, req_id, "fixed", "requirement_type",
                                    f"{rt!r} → {fixed!r}"))
        tc["requirement_type"] = fixed

    # scenario_type
    st = str(tc.get("scenario_type", "normal")).lower().strip()
    if st not in VALID_SCENARIO:
        fixed = "boundary"   if "bound" in st else \
                "edge"        if "edge" in st or "corner" in st else \
                "robustness"  if "robust" in st or "neg" in st else \
                "transition"  if "trans" in st else "normal"
        issues.append(TestCaseIssue(tc_id, req_id, "fixed", "scenario_type",
                                    f"{st!r} → {fixed!r}"))
        tc["scenario_type"] = fixed

    # testing_type
    tt = str(tc.get("testing_type", "verification")).lower().strip()
    if tt not in VALID_TESTING:
        fixed = "integration" if "integr" in tt else \
                "validation"   if "valid" in tt else "verification"
        issues.append(TestCaseIssue(tc_id, req_id, "fixed", "testing_type",
                                    f"{tt!r} → {fixed!r}"))
        tc["testing_type"] = fixed

    # list fields — ensure they are lists, not strings
    for lf in ("preconditions", "test_steps", "inputs"):
        v = tc.get(lf, [])
        if isinstance(v, str):
            tc[lf] = [v] if v.strip() else []
            if v.strip():
                issues.append(TestCaseIssue(tc_id, req_id, "fixed", lf,
                                            f"String converted to list"))

    return tc, issues


def _check_content(tc: dict, tc_id: str, req_id: str) -> List[TestCaseIssue]:
    issues = []

    # Critical content fields that must not be empty/placeholder
    critical = ["objective", "expected_outcome"]
    for f in critical:
        v = str(tc.get(f, "")).strip()
        if _is_empty(v):
            issues.append(TestCaseIssue(tc_id, req_id, "warning", f,
                                        f"Field '{f}' is empty or placeholder"))

    # test_steps must have at least one step
    steps = tc.get("test_steps", [])
    if not steps or (len(steps) == 1 and _is_empty(str(steps[0]))):
        issues.append(TestCaseIssue(tc_id, req_id, "warning", "test_steps",
                                    "No test steps defined"))

    # test_case_id should look like a real ID
    tc_id_val = str(tc.get("test_case_id", "")).strip()
    if _is_empty(tc_id_val) or tc_id_val in ("TC_AUTO", "?"):
        issues.append(TestCaseIssue(tc_id, req_id, "warning", "test_case_id",
                                    f"test_case_id is missing or auto-assigned: {tc_id_val!r}"))

    # Req 4: Input Values must be concrete, not unfilled placeholder text
    for entry in tc.get("inputs", []) or []:
        entry_str = str(entry)
        value = entry_str.split(":", 1)[-1].split("=", 1)[-1].strip() if (":" in entry_str or "=" in entry_str) else entry_str
        if value and GENERIC_INPUT_VALUE_PATTERNS.match(value.strip()):
            issues.append(TestCaseIssue(
                tc_id, req_id, "warning", "inputs",
                f"Input {entry_str!r} looks like an unfilled placeholder — "
                f"replace with the actual invalid/garbage value used for this test"
            ))

    return issues


def _is_empty(v: str) -> bool:
    return v.strip().lower() in EMPTY_LIKE or PLACEHOLDER_PATTERNS.match(v.strip()) is not None


def _fuzzy_req_match(rid: str, valid_ids: Set[str]) -> Optional[str]:
    """Try to find a close match for a req ID that doesn't exactly match."""
    rid_upper = rid.upper().strip()
    for valid in valid_ids:
        if valid.upper().strip() == rid_upper:
            return valid
    # Try stripping trailing zeros or whitespace differences
    rid_norm = re.sub(r'[\s_-]+', '_', rid_upper)
    for valid in valid_ids:
        if re.sub(r'[\s_-]+', '_', valid.upper()) == rid_norm:
            return valid
    return None
