from pydantic import BaseModel, field_validator
from typing import List, Literal, Dict, Optional


class TestCase(BaseModel):
    traceability_req_id: str
    test_case_id: str
    scenario_id: str
    priority: Literal["P1", "P2", "P3"]
    objective: str
    preconditions: List[str]
    test_steps: List[str]
    # Inputs now stored as named key=value pairs; plain list kept for compatibility
    inputs: List[str]
    design_methodology: str
    dependent_test_cases: str
    expected_outcome: str
    test_environment: Literal["Dev", "QA", "UAT", "Prod"]
    remarks: str
    module: str
    requirement_type: Literal["functional", "non-functional"]
    scenario_type: Literal["normal", "boundary", "edge", "robustness", "transition",
                           "mcdc", "beyond_range", "fault", "timing", "invalid_input"]
    testing_type: Literal["verification", "validation", "integration"]

    # ── Server-computed GUI display fields ───────────────────────────────────
    # Populated by output_generator.compute_gui_display_fields() before a
    # TestCase leaves the API layer. These mirror the narrative columns
    # written into the Excel/Word export exactly, so the GUI never has to
    # (and must not) re-derive this text itself. Optional so that TestCase
    # objects can still be constructed before these are computed.
    test_details_description:  Optional[str] = None
    test_precondition_display: Optional[str] = None
    expected_outputs_display:  Optional[str] = None
    depends_on_display:        Optional[str] = None
    remarks_display:           Optional[str] = None
    module_display:            Optional[str] = None

    # ── Standardized Test Case Template columns (GUI + Excel export) ────────
    # tc_id_display: merged TC_ID + Scenario_ID (e.g. "TC_001_SC_001")
    # inputs_display / outputs_display: consolidated "Name1=Value1; Name2=Value2"
    # requirement_type_display: "Functional" / "Non-Functional"
    # coverage_type_display: "Validation" / "Verification" / "Integration"
    # scenario_type_display: title-cased scenario_type as-is (no value collapsing)
    # safety_level / test_level / standard_reference: optional per-TC overrides.
    # When AI-generated (MCP path) supplies these directly (it knows the domain
    # from the skill it used), that value wins. Otherwise the session-level
    # `domain` default (see GenerateRequest.domain) is applied at display-compute
    # time — see output_generator.compute_gui_display_fields.
    tc_id_display:            Optional[str] = None
    inputs_display:           Optional[str] = None
    outputs_display:          Optional[str] = None
    requirement_type_display: Optional[str] = None
    coverage_type_display:    Optional[str] = None
    test_level_display:       Optional[str] = None
    scenario_type_display:    Optional[str] = None
    safety_level_display:     Optional[str] = None
    pass_fail_criteria:       Optional[str] = None
    configure_baseline:       Optional[str] = None
    standard_reference_display: Optional[str] = None

    # Optional per-TC overrides — settable by the MCP/Claude-AI generation
    # path (which knows the domain from the skill in use). The rule-based
    # engine leaves these None and relies on the session-level domain default.
    safety_level:       Optional[str] = None
    test_level:         Optional[str] = None
    standard_reference: Optional[str] = None

    @field_validator(
        "requirement_type", "scenario_type", "testing_type",
        "priority", "test_environment", mode="before"
    )
    def normalise(cls, v):
        return str(v).strip()


class TestSuite(BaseModel):
    test_cases: List[TestCase]


class DocumentChunk(BaseModel):
    chunk_index:      int
    module:           str
    requirement_type: Literal["functional", "non-functional"]
    requirement_ids:  List[str]
    content:          str
    parent_id:        Optional[str]  = None
    child_ids:        List[str]      = []
    is_sub_req:       bool           = False
    has_children:     bool           = False
    # NEW: notes, enum definitions, sub-requirement references, inter-req context
    notes_context:    str            = ""
    # NEW: ICD/supporting-document cross-reference. icd_context is the
    # canonical "Name | Type | Lo to Hi | Unit" text for every signal this
    # chunk references, appended to content so existing ICD-range regexes
    # in test_case_generator.py pick it up. icd_signals is the same data
    # as structured specs, used to drive full-range BVA/ECP generation
    # even when the requirement sentence has no explicit comparison.
    icd_context:      str            = ""
    icd_signals:      Dict[str, dict] = {}


class UploadResponse(BaseModel):
    session_id: str
    filename: str
    char_count: int
    text_preview: str


class MergeSessionsRequest(BaseModel):
    # Session ids returned by prior /api/upload calls, in the order the user
    # added them. All belong to the same logical document type (srs/icd).
    session_ids: List[str]
    doc_type: str = "srs"


class MergeSessionsResponse(BaseModel):
    session_id: str
    filename: str
    char_count: int
    text_preview: str
    source_session_ids: List[str]


class ReviewPoints(BaseModel):
    rp1: bool = True
    rp2: bool = True
    rp3: bool = True
    rp4: bool = True
    rp5: bool = True
    rp6: bool = False  # Smart Requirement Merging


class GenerateRequest(BaseModel):
    session_id: str
    review_points: ReviewPoints
    icd_session_id: Optional[str] = None
    supporting_session_id:  Optional[str]       = None   # kept for backward compat
    supporting_session_ids: Optional[List[str]]  = None   # multiple supporting docs
    # Scope filters — None means generate for all
    selected_req_ids: Optional[List[str]] = None
    selected_module:  Optional[str]       = None
    selected_modules: Optional[List[str]]  = None
    req_prefixes:     Optional[List[str]] = None
    # Domain selector for Safety_Level / Test_Level / Standard_Reference
    # defaults in the standardized template (see constants.DOMAIN_DEFAULTS).
    # Editable after generation — this is a starting point, not a
    # per-requirement DAL/ASIL classification.
    domain: Literal["avionics", "automotive", "healthcare", "general"] = "general"


class GenerateSummary(BaseModel):
    total: int
    by_module: Dict[str, int]
    by_requirement_type: Dict[str, int]
    by_scenario_type: Dict[str, int]
    by_testing_type: Dict[str, int]
    by_priority: Dict[str, int]
    duplicates_removed: int
    # Coverage against the in-scope SRS requirement set
    requirements_total: int = 0
    requirements_covered: int = 0


class GenerateResponse(BaseModel):
    test_cases: List[TestCase]
    summary: GenerateSummary


class HealthResponse(BaseModel):
    status: str
    engine: str
    spacy_available: bool
    version: str


class ErrorDetail(BaseModel):
    error: str
    layer: str
    detail: str
    retry_count: int
    suggestion: str