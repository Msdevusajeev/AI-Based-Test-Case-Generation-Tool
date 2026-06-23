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
    scenario_type: Literal["normal", "boundary", "edge", "robustness", "transition"]
    testing_type: Literal["verification", "validation", "integration"]

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


class UploadResponse(BaseModel):
    session_id: str
    filename: str
    char_count: int
    text_preview: str


class ReviewPoints(BaseModel):
    rp1: bool = True
    rp2: bool = True
    rp3: bool = True
    rp4: bool = True
    rp5: bool = True


class GenerateRequest(BaseModel):
    session_id: str
    review_points: ReviewPoints
    icd_session_id: Optional[str] = None
    supporting_session_id:  Optional[str]       = None   # kept for backward compat
    supporting_session_ids: Optional[List[str]]  = None   # multiple supporting docs
    # Scope filters — None means generate for all
    selected_req_ids: Optional[List[str]] = None
    selected_module:  Optional[str]       = None
    req_prefixes:     Optional[List[str]] = None


class GenerateSummary(BaseModel):
    total: int
    by_module: Dict[str, int]
    by_requirement_type: Dict[str, int]
    by_scenario_type: Dict[str, int]
    by_testing_type: Dict[str, int]
    by_priority: Dict[str, int]
    duplicates_removed: int


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