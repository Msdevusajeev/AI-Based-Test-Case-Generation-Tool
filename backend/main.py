import logging
import os
import re
import sys
import threading
import traceback
import uuid
import webbrowser
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Dict, Any

from fastapi import FastAPI, UploadFile, File, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

# ── Fix: when frozen (console=False) stdout/stderr are None ──────────────────
# Redirect them to a log file so uvicorn logging doesn't crash with
# AttributeError: 'NoneType' object has no attribute 'isatty'
if getattr(sys, 'frozen', False):
    _log_path = os.path.join(os.path.dirname(sys.executable), 'TestCaseGenerator.log')
    _log_file = open(_log_path, 'w', buffering=1, encoding='utf-8')
    sys.stdout = _log_file
    sys.stderr = _log_file

# ── Resolve paths whether running as .py or as a PyInstaller .exe ────────────
if getattr(sys, 'frozen', False):
    BASE_DIR = Path(sys._MEIPASS)
else:
    BASE_DIR = Path(__file__).resolve().parent.parent

from models import (
    UploadResponse, GenerateRequest, GenerateResponse,
    GenerateSummary, HealthResponse, ReviewPoints,
)
from config import ENGINE, VERSION, CHUNK_SIZE_WORDS, MCP_ENABLED
from file_parser import parse_file
from document_ingestion import ingest_document
from test_case_generator import generate_all, is_spacy_available
from output_generator import generate_excel, generate_docx

# ─── LOGGING ──────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

# ─── APP ──────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Rule-Based Test Case Generator",
    version=VERSION,
    description=(
        "Generates test cases from SRS documents using pure rule-based NLP — "
        "no API, no LLM. Optionally enhances with Claude Desktop via MCP."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── SESSION STORE ────────────────────────────────────────────────────────────
# In-memory store: session_id → { filename, doc_type, text, chunks, test_cases, removed }
sessions: Dict[str, Dict[str, Any]] = {}

# ─── MCP RESULTS STORE ────────────────────────────────────────────────────────
# Claude Desktop writes here via /api/mcp/save
# React UI reads via /api/mcp/latest
mcp_results_store: Dict[str, Any] = {
    "test_cases": [],
    "summary":    None,
    "timestamp":  None,
}

# ─── AI GENERATION QUEUE ──────────────────────────────────────────────────────
# React UI writes chunks here → Claude Desktop reads via MCP
# ── Token usage tracking (estimated — Claude Desktop does not expose exact "
# usage to MCP servers, so we estimate from payload sizes using the standard
# ~4 chars/token heuristic for English text) ─────────────────────────────────
token_usage: Dict[str, Any] = {
    "session_id":      None,
    "input_tokens_est":  0,
    "output_tokens_est": 0,
    "context_budget":   200_000,  # Claude Desktop context window
    "calls_made":       0,
}

def _estimate_tokens(text: str) -> int:
    """Rough token estimate using ~4 chars/token heuristic (Claude-family average)."""
    return max(1, len(text) // 4)


generation_queue: Dict[str, Any] = {
    "chunks":     [],
    "session_id": None,
    "status":     "idle",   # idle / queued / complete
}


# ─── MCP RESULT NORMALISER ────────────────────────────────────────────────────

def _normalise_mcp_tc(raw: dict) -> dict:
    """
    Normalises a raw dict from Claude AI into a valid TestCase-compatible dict.
    Handles field name variations and Literal value mismatches.
    """
    aliases = {
        "steps":               "test_steps",
        "test_step":           "test_steps",
        "teststeps":           "test_steps",
        "precondition":        "preconditions",
        "pre_conditions":      "preconditions",
        "pre-conditions":      "preconditions",
        "test_objective":      "objective",
        "description":         "objective",
        "req_id":              "traceability_req_id",
        "requirement_id":      "traceability_req_id",
        "traceability":        "traceability_req_id",
        "tc_id":               "test_case_id",
        "id":                  "test_case_id",
        "scenario_no":         "scenario_id",
        "scenario_number":     "scenario_id",
        "methodology":         "design_methodology",
        "test_methodology":    "design_methodology",
        "dependent":           "dependent_test_cases",
        "depends_on":          "dependent_test_cases",
        "depands_on":          "dependent_test_cases",
        "expected":            "expected_outcome",
        "expected_result":     "expected_outcome",
        "environment":         "test_environment",
        "test_env":            "test_environment",
        "req_type":            "requirement_type",
    }
    tc = {}
    for k, v in raw.items():
        key = aliases.get(k.lower().replace(" ", "_"), k)
        tc[key] = v

    # priority → P1 / P2 / P3
    p = str(tc.get("priority", "P1")).upper()
    if p in ("P1", "HIGH", "CRITICAL", "MUST"):      tc["priority"] = "P1"
    elif p in ("P2", "MEDIUM", "SHOULD"):             tc["priority"] = "P2"
    elif p in ("P3", "LOW", "COULD", "NICE"):         tc["priority"] = "P3"
    else:                                             tc["priority"] = "P1"

    env = str(tc.get("test_environment", "Dev")).lower()
    if   "prod" in env:                               tc["test_environment"] = "Prod"
    elif "uat"  in env or "accept" in env:            tc["test_environment"] = "UAT"
    elif "qa"   in env or "test"   in env:            tc["test_environment"] = "QA"
    else:                                             tc["test_environment"] = "Dev"

    rt = str(tc.get("requirement_type", "functional")).lower()
    if "non" in rt or "nonfunc" in rt:               tc["requirement_type"] = "non-functional"
    else:                                             tc["requirement_type"] = "functional"

    st = str(tc.get("scenario_type", "normal")).lower()
    if   "bound"   in st:                            tc["scenario_type"] = "boundary"
    elif "edge"    in st or "corner" in st:          tc["scenario_type"] = "edge"
    elif "robust"  in st or "negative" in st:        tc["scenario_type"] = "robustness"
    else:                                             tc["scenario_type"] = "normal"

    tt = str(tc.get("testing_type", "verification")).lower()
    if   "integr" in tt:                             tc["testing_type"] = "integration"
    elif "valid"  in tt:                             tc["testing_type"] = "validation"
    else:                                             tc["testing_type"] = "verification"

    for list_field in ("preconditions", "test_steps", "inputs"):
        val = tc.get(list_field, [])
        if isinstance(val, str):
            tc[list_field] = [v.strip() for v in val.split("\n") if v.strip()]
        elif not isinstance(val, list):
            tc[list_field] = [str(val)] if val else []

    # Normalise input signal names: collapse whitespace and strip scenario-type
    # qualifiers that Claude AI sometimes appends when generating multiple TCs
    # (normal / boundary / edge / robustness) for the same requirement.
    # This ensures "CondA (boundary): False" and "CondA: True" both map to
    # the single "CondA" column rather than creating two separate columns.
    _QUAL_RE = re.compile(
        r"\s*[\(\[]\s*(?:normal|boundary|edge|robustness|positive|negative|"
        r"baseline|flip|invalid|valid|min|max|minimum|maximum)\s*[\)\]]"
        r"|\s*[-_]\s*(?:normal|boundary|edge|robustness|positive|negative|"
        r"baseline|flip|invalid|valid|min|max|minimum|maximum)\s*$",
        re.IGNORECASE,
    )
    normalised_inputs = []
    for entry in tc.get("inputs", []):
        if not isinstance(entry, str):
            entry = str(entry)
        sep = ":" if ":" in entry else ("=" if "=" in entry else None)
        if sep:
            parts = entry.split(sep, 1)
            raw_name  = parts[0].strip()
            raw_value = parts[1].strip() if len(parts) > 1 else ""
            # Strip scenario qualifier from name and normalise whitespace
            clean_name = re.sub(r"\s+", " ", _QUAL_RE.sub("", raw_name).strip())
            entry = f"{clean_name}{sep} {raw_value}" if raw_value else clean_name
        normalised_inputs.append(entry)
    tc["inputs"] = normalised_inputs

    defaults = {
        "traceability_req_id":  "REQ-001",
        "test_case_id":         "TC_UT_001",
        "scenario_id":          "SC-001",
        "objective":            "",
        "design_methodology":   "Black Box Testing",
        "dependent_test_cases": "None",
        "expected_outcome":     "",
        "remarks":              "",
        "module":               "General",
    }
    for field, default in defaults.items():
        if not tc.get(field):
            tc[field] = default

    return tc


# ─── ERROR HELPER ─────────────────────────────────────────────────────────────

def _error(error: str, layer: str, detail: str, suggestion: str, status: int = 500):
    raise HTTPException(
        status_code=status,
        detail={
            "error":       error,
            "layer":       layer,
            "detail":      detail,
            "retry_count": 0,
            "suggestion":  suggestion,
        },
    )


# ─── HEALTH ───────────────────────────────────────────────────────────────────

@app.get("/api/health", response_model=HealthResponse)
def health():
    return HealthResponse(
        status="ok",
        engine=ENGINE,
        spacy_available=is_spacy_available(),
        version=VERSION,
    )


# ─── MODE ─────────────────────────────────────────────────────────────────────

@app.get("/api/mode")
def get_mode():
    """Returns current engine mode. Frontend uses this to show mode indicator."""
    if MCP_ENABLED:
        return {
            "mode":        "online",
            "engine":      "Claude Desktop MCP",
            "description": "AI-enhanced generation via Claude Desktop",
        }
    return {
        "mode":        "offline",
        "engine":      "Rule-Based NLP",
        "description": "Offline rule-based generation",
    }


# ─── DEBUG ────────────────────────────────────────────────────────────────────

@app.get("/api/debug/chunks")
def debug_chunks(session_id: str = Query(...)):
    session = sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")
    text   = session.get("text", "")
    chunks = ingest_document(text)
    return {
        "total_chunks": len(chunks),
        "chunks": [
            {
                "chunk_index":      c.chunk_index,
                "requirement_id":   c.requirement_ids[0] if c.requirement_ids else "REQ-001",
                "requirement_ids":  c.requirement_ids,
                "module":           c.module or "General",
                "requirement_type": c.requirement_type,
                "content":          c.content,
                "content_preview":  c.content[:150],
            }
            for c in chunks
        ],
    }


# ─── UPLOAD ───────────────────────────────────────────────────────────────────

@app.post("/api/upload", response_model=UploadResponse)
async def upload(file: UploadFile = File(...), doc_type: str = "srs"):
    """
    Upload a document (SRS, ICD, or supporting).
    doc_type: 'srs' | 'icd' | 'supporting'
    All uploaded texts are merged for generation; SRS requirements drive TC_IDs.
    """
    allowed = {".pdf", ".docx", ".doc", ".xlsx", ".xls"}
    suffix  = f".{file.filename.lower().rsplit('.', 1)[-1]}" if "." in file.filename else ""
    if suffix not in allowed:
        _error(
            "Unsupported file type",
            "parsing",
            f"Received: {suffix}",
            "Upload a .pdf, .docx, or .xlsx file",
            400,
        )

    try:
        raw_bytes = await file.read()
        text      = parse_file(file.filename, raw_bytes)
    except Exception as e:
        _error(
            "File parsing failed",
            "parsing",
            traceback.format_exc(),
            "Re-upload the file. PDF may be password-protected or empty.",
            422,
        )

    if not text or len(text.strip()) < 50:
        _error(
            "Document appears empty",
            "parsing",
            "Extracted text is too short",
            "Ensure the document has readable text content.",
            422,
        )

    session_id = str(uuid.uuid4())
    sessions[session_id] = {
        "filename":   file.filename,
        "doc_type":   doc_type,
        "text":       text,
        "chunks":     None,
        "test_cases": None,
        "removed":    0,
    }

    return UploadResponse(
        session_id   = session_id,
        filename     = file.filename,
        char_count   = len(text),
        text_preview = text[:500],
    )


# ─── GENERATE ─────────────────────────────────────────────────────────────────

@app.get("/api/scope")
def get_scope(session_id: str = Query(...), req_prefixes: str = Query(default="")):
    """
    Returns requirement IDs and modules found in the uploaded SRS document.
    If req_prefixes is provided (comma-separated), only IDs matching those
    prefixes are returned — this is what populates the Configure tab scope list.
    """
    session = sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    text   = session.get("text", "")
    chunks = ingest_document(text)

    # Apply prefix filter if provided
    prefixes = [p.strip() for p in req_prefixes.split(",") if p.strip()] if req_prefixes else []
    if prefixes:
        before = len(chunks)
        chunks = [c for c in chunks
                  if c.requirement_ids and
                  any(c.requirement_ids[0].startswith(px) for px in prefixes)]
        logger.info(f"[SCOPE-FILTER] prefixes={prefixes} → {before} → {len(chunks)} chunks")

    req_ids: list = []
    modules: list = []
    seen_r:  set  = set()
    seen_m:  set  = set()

    for c in sorted(chunks, key=lambda x: (x.requirement_ids[0] if x.requirement_ids else "")):
        rid = c.requirement_ids[0] if c.requirement_ids else None
        if rid and rid not in seen_r:
            seen_r.add(rid)
            req_ids.append(rid)
        mod = c.module or "General"
        if mod not in seen_m:
            seen_m.add(mod)
            modules.append(mod)

    return {"requirement_ids": req_ids, "modules": sorted(modules)}


# ─────────────────────────────────────────────────────────────────────────────

@app.post("/api/generate", response_model=GenerateResponse)
def generate(request: GenerateRequest):
    session = sessions.get(request.session_id)
    if not session:
        _error("Session not found", "generation", "", "Upload a file first.", 404)

    try:
        text = session["text"]

        # Merge ICD and supporting texts for comprehensive input extraction (Req 1 & 4)
        icd_text = ""
        if request.icd_session_id and request.icd_session_id in sessions:
            icd_text = sessions[request.icd_session_id].get("text", "")
        supporting_text = ""
        if request.supporting_session_id and request.supporting_session_id in sessions:
            supporting_text = sessions[request.supporting_session_id].get("text", "")

        combined_text = text
        if icd_text:
            combined_text += f"\n\n[ICD_DOCUMENT_START]\n{icd_text}\n[ICD_DOCUMENT_END]"
        if supporting_text:
            combined_text += f"\n\n[SUPPORTING_DOCUMENT_START]\n{supporting_text}\n[SUPPORTING_DOCUMENT_END]"

        # Ingest SRS ONLY — ICD/supporting text contains identifiers that
        # confuse the parser and create phantom requirement chunks.
        chunks = ingest_document(text, CHUNK_SIZE_WORDS)

        # ── Scope filter ─────────────────────────────────────────────────────
        # If the user selected specific requirement IDs, keep only those chunks.
        # If the user selected a module, keep only chunks for that module.
        logger.info(f"[SCOPE] selected_req_ids={request.selected_req_ids!r}  "
                    f"selected_module={request.selected_module!r}  "
                    f"total_chunks={len(chunks)}")

        # IMPORTANT: use `is not None` — empty list [] is falsy in Python
        if request.selected_req_ids is not None:
            keep   = set(request.selected_req_ids)
            before = len(chunks)
            chunks = [c for c in chunks
                      if any(rid in keep for rid in c.requirement_ids)]
            logger.info(f"[SCOPE] req filter → {before} → {len(chunks)} chunks | keep={keep}")
        elif request.selected_module and request.selected_module != "__all__":
            before = len(chunks)
            chunks = [c for c in chunks
                      if (c.module or "General") == request.selected_module]
            logger.info(f"[SCOPE] module filter → {before} → {len(chunks)} chunks")
        else:
            logger.info(f"[SCOPE] no filter — generating for all {len(chunks)} chunks")
        # ─────────────────────────────────────────────────────────────────────

        if not chunks:
            _error(
                "No requirements found",
                "ingestion",
                "Document produced zero chunks",
                "Verify SRS language uses shall/must/should and contains requirement sentences.",
                422,
            )

        rp = request.review_points
        review_points = {
            "rp1": rp.rp1,
            "rp2": rp.rp2,
            "rp3": rp.rp3,
            "rp4": rp.rp4,
            "rp5": rp.rp5,
        }

        # Rule-based engine ONLY — Claude AI uses /api/generate/ai (separate endpoint)
        try:
            test_cases, removed = generate_all(chunks, review_points)
        except Exception:
            import traceback
            logger.error(f"Generation error: {traceback.format_exc()}")
            raise

        if not test_cases:
            _error(
                "No test cases generated",
                "generation",
                "Generator produced zero test cases",
                "No requirement sentences matched keyword patterns. "
                "Verify SRS language uses shall/must/should.",
                422,
            )

        sessions[request.session_id]["chunks"]     = chunks
        sessions[request.session_id]["test_cases"] = test_cases
        sessions[request.session_id]["removed"]    = removed

        summary = GenerateSummary(
            total               = len(test_cases),
            by_module           = dict(Counter(tc.module           for tc in test_cases)),
            by_requirement_type = dict(Counter(tc.requirement_type for tc in test_cases)),
            by_scenario_type    = dict(Counter(tc.scenario_type    for tc in test_cases)),
            by_testing_type     = dict(Counter(tc.testing_type     for tc in test_cases)),
            by_priority         = dict(Counter(tc.priority         for tc in test_cases)),
            duplicates_removed  = removed,
        )

        return GenerateResponse(test_cases=test_cases, summary=summary)

    except HTTPException:
        raise
    except Exception as e:
        _error(
            "Generation failed",
            "generation",
            traceback.format_exc(),
            "Check server logs for details.",
        )



# ── DEBUG: store last AI generate request ────────────────────────────────────
_last_ai_request: dict = {}

@app.get("/api/debug/last-request")
async def debug_last_request():
    """Shows what the last /api/generate/ai call received."""
    return _last_ai_request
# ─────────────────────────────────────────────────────────────────────────────



# ── Module-based generation progress tracking ─────────────────────────────────
_module_progress: dict = {}   # {session_id: {module_name: "pending"|"done"}}

@app.get("/api/session/modules")
async def get_session_modules(session_id: str, req_prefixes: str = ""):
    """Returns all modules in the session with req counts. Use for module-by-module generation."""
    session = sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    text = session.get("text", "")
    chunks = ingest_document(text)
    prefixes = [p.strip() for p in req_prefixes.split(",") if p.strip()] if req_prefixes else []
    if prefixes:
        chunks = [c for c in chunks if c.requirement_ids and
                  any(c.requirement_ids[0].startswith(px) for px in prefixes)]
    from collections import Counter
    module_counts = Counter(c.module or "General" for c in chunks)
    progress = _module_progress.get(session_id, {})
    return {
        "total_requirements": len(chunks),
        "total_modules": len(module_counts),
        "modules": [
            {
                "name": mod,
                "req_count": count,
                "status": progress.get(mod, "pending"),
            }
            for mod, count in sorted(module_counts.items(), key=lambda x: -x[1])
        ],
    }


@app.post("/api/session/module_done")
async def mark_module_done(request: Request):
    """Mark a module as done after its test cases are saved."""
    data = await request.json()
    session_id = data.get("session_id")
    module_name = data.get("module")
    if session_id and module_name:
        if session_id not in _module_progress:
            _module_progress[session_id] = {}
        _module_progress[session_id][module_name] = "done"
    return {"status": "ok", "module": module_name}


@app.get("/api/session/progress")
async def get_progress(session_id: str):
    """Returns which modules are done vs pending."""
    return _module_progress.get(session_id, {})

# ─────────────────────────────────────────────────────────────────────────────

# ── DEBUG endpoint: shows exactly what ingest_document returns ───────────────
@app.get("/api/debug/ingest")
async def debug_ingest(session_id: str, req_prefix: str = ""):
    """Call with ?session_id=XXX&req_prefix=MRJ_SCU_STC_SRS_"""
    session = sessions.get(session_id)
    if not session:
        return {"error": "session not found", "available": list(sessions.keys())}
    text = session.get("text", "")
    chunks = ingest_document(text)
    all_ids = [c.requirement_ids[0] if c.requirement_ids else "?" for c in chunks]
    filtered = [i for i in all_ids if i.startswith(req_prefix)] if req_prefix else all_ids
    return {
        "total_chunks": len(chunks),
        "total_matching_prefix": len(filtered),
        "prefix_used": req_prefix,
        "first_20_all_ids": all_ids[:20],
        "first_20_filtered": filtered[:20],
        "document_ingestion_file": __import__('document_ingestion').__file__,
    }
# ─────────────────────────────────────────────────────────────────────────────

# ─── GENERATE (Claude AI) ─────────────────────────────────────────────────────

@app.post("/api/generate/ai")
async def generate_ai(request: Request):
    """
    Claude AI generation endpoint — triggered exclusively by the
    "Generate Test Cases using Claude AI" button.

    Ingests the uploaded document, extracts requirement chunks, queues them
    for Claude Desktop (via MCP), and returns the queued chunk count.
    Claude Desktop processes them asynchronously; the React UI polls
    /api/ai/status and /api/mcp/latest to detect when results are ready.

    The rule-based engine is NOT called here.
    """
    try:
        data       = await request.json()
        session_id = data.get("session_id")

        # ── DEBUG: store and log incoming payload ─────────────────────────
        _last_ai_request.clear()
        _last_ai_request.update({
            "keys":        list(data.keys()),
            "req_prefixes": data.get("req_prefixes"),
            "session_id":  session_id,
        })
        logger.info(
            f"[AI-ENDPOINT] incoming keys={list(data.keys())} | "
            f"req_prefixes={data.get('req_prefixes')!r} | "
            f"selected_req_ids={data.get('selected_req_ids')!r} | "
            f"session_id={session_id!r}"
        )
        # ─────────────────────────────────────────────────────────────────

        if not session_id:
            raise HTTPException(status_code=400, detail="session_id is required")

        session = sessions.get(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found. Upload a file first.")

        text = session["text"]

        icd_text = ""
        icd_session_id = data.get("icd_session_id")
        if icd_session_id and icd_session_id in sessions:
            icd_text = sessions[icd_session_id].get("text", "")

        supporting_text = ""
        supporting_session_id = data.get("supporting_session_id")
        if supporting_session_id and supporting_session_id in sessions:
            supporting_text = sessions[supporting_session_id].get("text", "")

        combined_text = text
        if icd_text:
            combined_text += f"\n\n[ICD_DOCUMENT_START]\n{icd_text}\n[ICD_DOCUMENT_END]"
        if supporting_text:
            combined_text += f"\n\n[SUPPORTING_DOCUMENT_START]\n{supporting_text}\n[SUPPORTING_DOCUMENT_END]"

        # Ingest SRS ONLY — ICD/supporting text contains identifiers that
        # confuse the parser and create phantom requirement chunks.
        chunks = ingest_document(text, CHUNK_SIZE_WORDS)

        # ── Scope filter for Claude AI (same logic as rule-based) ─────────────
        selected_req_ids = data.get("selected_req_ids")   # list or None
        selected_module  = data.get("selected_module")    # str or None

        # ── Requirement ID prefix filter ─────────────────────────────────
        req_prefixes = data.get("req_prefixes") or []
        if req_prefixes:
            prefixes = [p.strip() for p in req_prefixes if p.strip()]
            if prefixes:
                before_pf = len(chunks)
                chunks = [c for c in chunks
                          if c.requirement_ids and
                          any(c.requirement_ids[0].startswith(px) for px in prefixes)]
                logger.info(f"[PREFIX/AI] {prefixes} → {before_pf} → {len(chunks)} chunks")
        # ─────────────────────────────────────────────────────────────────

        logger.info(f"[SCOPE/AI] selected_req_ids={selected_req_ids!r}  "
                    f"selected_module={selected_module!r}  "
                    f"total_chunks={len(chunks)}")

        if selected_req_ids is not None:
            keep   = set(selected_req_ids)
            before = len(chunks)
            # Keep chunk if ANY of its requirement IDs is in the selected set
            chunks = [c for c in chunks
                      if any(rid in keep for rid in (c.requirement_ids or []))]
            logger.info(f"[SCOPE/AI] req filter → {before} → {len(chunks)} chunks | keep={keep}")
        elif selected_module and selected_module != "__all__":
            before = len(chunks)
            chunks = [c for c in chunks
                      if (c.module or "General") == selected_module]
            logger.info(f"[SCOPE/AI] module filter → {before} → {len(chunks)} chunks")
        else:
            logger.info(f"[SCOPE/AI] no filter — queuing all {len(chunks)} chunks")
        # ─────────────────────────────────────────────────────────────────────

        if not chunks:
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "No requirements found",
                    "suggestion": "Verify SRS language uses shall/must/should.",
                },
            )

        # Expand: one entry per requirement ID so Claude gets context for EVERY
        # requirement even when multiple reqs share the same module/chunk.
        # Use _extract_req_content to isolate each requirement's text so
        # signals and conditions from sibling requirements don't bleed through.
        chunk_data = []
        for c in chunks:
            # Use ONLY the primary ID — body-text cross-references inflate the count
            req_id = c.requirement_ids[0] if c.requirement_ids else "REQ-001"
            chunk_data.append({
                "requirement_id":   req_id,
                "content":          c.content,
                "module":           c.module or "General",
                "requirement_type": c.requirement_type,
            })

        # Store chunks in session for reference and queue for Claude AI
        sessions[session_id]["chunks"] = chunks
        generation_queue["chunks"]     = chunk_data
        generation_queue["session_id"] = session_id
        generation_queue["status"]     = "queued"

        # Clear any stale MCP results so the UI does not show old data
        mcp_results_store["test_cases"] = []
        mcp_results_store["summary"]    = None
        mcp_results_store["timestamp"]  = None

        logger.info(
            f"AI generation queued: {len(chunk_data)} chunks "
            f"(session={session_id})"
        )
        return {
            "status":       "queued",
            "total_chunks": len(chunk_data),
            "session_id":   session_id,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"AI queue error: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))


# ─── EXPORT ───────────────────────────────────────────────────────────────────

@app.get("/api/export/excel")
def export_excel(session_id: str = Query(...)):
    session = sessions.get(session_id)
    if not session or not session.get("test_cases"):
        _error("No generated test cases found", "export", "", "Run /api/generate first.", 404)

    try:
        xlsx_bytes = generate_excel(session["test_cases"], session["removed"])
    except Exception as e:
        _error("Excel export failed", "export", traceback.format_exc(), "Check server logs.")

    return Response(
        content    = xlsx_bytes,
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers    = {"Content-Disposition": "attachment; filename=test_cases.xlsx"},
    )


@app.get("/api/export/docx")
def export_docx(session_id: str = Query(...)):
    session = sessions.get(session_id)
    if not session or not session.get("test_cases"):
        _error("No generated test cases found", "export", "", "Run /api/generate first.", 404)

    try:
        docx_bytes = generate_docx(session["test_cases"], session["removed"])
    except Exception as e:
        _error("Word export failed", "export", traceback.format_exc(), "Check server logs.")

    return Response(
        content    = docx_bytes,
        media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers    = {"Content-Disposition": "attachment; filename=test_cases.docx"},
    )


# ─── MCP RESULTS ──────────────────────────────────────────────────────────────

@app.get("/api/mcp/latest")
def get_mcp_latest():
    """Returns latest test cases generated via Claude Desktop MCP.
    React UI polls this every 3 seconds to detect new results."""
    if not mcp_results_store["test_cases"]:
        return {"available": False, "test_cases": [], "summary": None}
    return {
        "available":  True,
        "test_cases": mcp_results_store["test_cases"],
        "summary":    mcp_results_store["summary"],
        "timestamp":  mcp_results_store["timestamp"],
    }


@app.post("/api/mcp/save")
async def save_mcp_results(request: Request):
    """Called by mcp_server.py after Claude Desktop generates test cases.
    Stores results so React UI can display and download them"""
    data = await request.json()
    mcp_results_store["test_cases"] = data.get("test_cases", [])
    mcp_results_store["summary"]    = data.get("summary", {})
    mcp_results_store["timestamp"]  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    generation_queue["status"]      = "complete"
    logger.info(f"MCP results saved: {len(mcp_results_store['test_cases'])} test cases")
    return {"status": "saved", "total": len(mcp_results_store["test_cases"])}


# ── Chunked save endpoints for large test case batches ───────────────────────
# mcp_server.py calls these instead of /api/mcp/save when is_partial is used,
# so each MCP call stays well under the 1MB payload limit.
_chunk_buffer: list = []

@app.post("/api/mcp/save_chunk")
async def save_chunk(request: Request):
    """Receives one batch of test cases. Buffers them in memory.
    Called once per batch. Use is_last=True on the final batch."""
    global _chunk_buffer
    data = await request.json()
    chunk = data.get("test_cases", [])
    is_last = data.get("is_last", False)
    _chunk_buffer.extend(chunk)
    logger.info(f"[CHUNK SAVE] +{len(chunk)} test cases | buffer_total={len(_chunk_buffer)} | is_last={is_last}")
    return {"status": "chunk_received", "buffer_total": len(_chunk_buffer), "is_last": is_last}


@app.post("/api/mcp/save_finalise")
async def save_finalise():
    """Merges all buffered chunks into mcp_results_store and completes the queue.
    Called once after the final batch's save_chunk."""
    global _chunk_buffer
    from collections import Counter

    test_cases = list(_chunk_buffer)
    _chunk_buffer = []

    if not test_cases:
        raise HTTPException(status_code=400, detail="No chunks buffered. Send chunks via save_chunk first.")

    summary = {
        "total":               len(test_cases),
        "duplicates_removed":  0,
        "by_module":           dict(Counter(tc.get("module", "General")            for tc in test_cases)),
        "by_requirement_type": dict(Counter(tc.get("requirement_type", "functional") for tc in test_cases)),
        "by_scenario_type":    dict(Counter(tc.get("scenario_type", "normal")        for tc in test_cases)),
        "by_testing_type":     dict(Counter(tc.get("testing_type", "verification")   for tc in test_cases)),
        "by_priority":         dict(Counter(tc.get("priority", "P1")                 for tc in test_cases)),
    }

    mcp_results_store["test_cases"] = test_cases
    mcp_results_store["summary"]    = summary
    mcp_results_store["timestamp"]  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    generation_queue["status"]      = "complete"

    logger.info(f"[FINALISE] Saved {len(test_cases)} test cases from chunked upload")
    return {"status": "finalised", "total": len(test_cases), "summary": summary}
# ─────────────────────────────────────────────────────────────────────────────


@app.get("/api/export/excel/mcp")
def export_mcp_excel():
    """Exports Claude Desktop MCP results as Excel"""
    if not mcp_results_store["test_cases"]:
        raise HTTPException(status_code=404,
            detail="No results found. Generate test cases with Claude first, then click Load Results.")
    from models import TestCase
    try:
        DEFAULTS = {
            "traceability_req_id": "", "test_case_id": "", "scenario_id": "",
            "priority": "P2", "objective": "", "preconditions": [],
            "test_steps": [], "inputs": [], "design_methodology": "Equivalence Partitioning",
            "dependent_test_cases": "None", "expected_outcome": "",
            "test_environment": "Dev", "remarks": "", "module": "General",
            "requirement_type": "functional", "scenario_type": "normal",
            "testing_type": "verification",
        }
        test_cases = []
        for raw in mcp_results_store["test_cases"]:
            merged = {**DEFAULTS, **{k: v for k, v in raw.items() if k in DEFAULTS}}
            try:
                test_cases.append(TestCase(**merged))
            except Exception:
                logger.warning(f"Skipping malformed test case: {raw.get('test_case_id','?')} — {traceback.format_exc()}")
        if not test_cases:
            raise HTTPException(status_code=422, detail="Test cases could not be parsed. Check Claude output format.")
        xlsx_bytes = generate_excel(test_cases, 0)
        return Response(
            content    = xlsx_bytes,
            media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers    = {"Content-Disposition": "attachment; filename=test_cases_claude.xlsx"},
        )
    except HTTPException:
        raise
    except Exception:
        logger.error(f"MCP Excel export error: {traceback.format_exc()}")
        _error("Excel export failed", "export", traceback.format_exc(), "Check server logs.")


@app.get("/api/export/docx/mcp")
def export_mcp_docx():
    """Exports Claude Desktop MCP results as Word"""
    if not mcp_results_store["test_cases"]:
        raise HTTPException(status_code=404,
            detail="No results found. Generate test cases with Claude first, then click Load Results.")
    from models import TestCase
    try:
        DEFAULTS = {
            "traceability_req_id": "", "test_case_id": "", "scenario_id": "",
            "priority": "P2", "objective": "", "preconditions": [],
            "test_steps": [], "inputs": [], "design_methodology": "Equivalence Partitioning",
            "dependent_test_cases": "None", "expected_outcome": "",
            "test_environment": "Dev", "remarks": "", "module": "General",
            "requirement_type": "functional", "scenario_type": "normal",
            "testing_type": "verification",
        }
        test_cases = []
        for raw in mcp_results_store["test_cases"]:
            merged = {**DEFAULTS, **{k: v for k, v in raw.items() if k in DEFAULTS}}
            try:
                test_cases.append(TestCase(**merged))
            except Exception:
                logger.warning(f"Skipping malformed test case: {raw.get('test_case_id','?')} — {traceback.format_exc()}")
        if not test_cases:
            raise HTTPException(status_code=422, detail="Test cases could not be parsed. Check Claude output format.")
        docx_bytes = generate_docx(test_cases, 0)
        return Response(
            content    = docx_bytes,
            media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers    = {"Content-Disposition": "attachment; filename=test_cases_claude.docx"},
        )
    except HTTPException:
        raise
    except Exception:
        logger.error(f"MCP Word export error: {traceback.format_exc()}")
        _error("Word export failed", "export", traceback.format_exc(), "Check server logs.")


# ─── AI GENERATION QUEUE ──────────────────────────────────────────────────────

@app.get("/api/ai/queue")
def get_ai_queue():
    """Claude Desktop MCP server calls this to get pending requirements."""
    return {
        "chunks": generation_queue["chunks"],
        "status": generation_queue["status"],
        "total":  len(generation_queue["chunks"]),
    }


@app.post("/api/tokens/report")
async def report_tokens(request: Request):
    """
    mcp_server.py calls this after each get_generated_test_cases / 
    save_enhanced_test_cases call to report estimated token usage.
    """
    data = await request.json()
    direction = data.get("direction")  # "input" or "output"
    chars     = data.get("chars", 0)
    est_tokens = _estimate_tokens(" " * chars)  # reuse same heuristic via char count

    if token_usage["session_id"] != data.get("session_id"):
        # New session — reset counters
        token_usage["session_id"]        = data.get("session_id")
        token_usage["input_tokens_est"]  = 0
        token_usage["output_tokens_est"] = 0
        token_usage["calls_made"]        = 0

    if direction == "input":
        token_usage["input_tokens_est"] += est_tokens
    elif direction == "output":
        token_usage["output_tokens_est"] += est_tokens
    token_usage["calls_made"] += 1

    return {"status": "ok", **token_usage}


@app.get("/api/tokens/usage")
def get_token_usage():
    """Frontend polls this to show live token usage in the Generate tab."""
    total_used = token_usage["input_tokens_est"] + token_usage["output_tokens_est"]
    budget     = token_usage["context_budget"]
    return {
        **token_usage,
        "total_tokens_est": total_used,
        "tokens_remaining_est": max(0, budget - total_used),
        "percent_used": round(min(100, (total_used / budget) * 100), 1),
    }


@app.post("/api/ai/queue")
async def post_ai_queue(request: Request):
    """React UI posts chunks here for Claude Desktop to process."""
    data = await request.json()
    generation_queue["chunks"]     = data.get("chunks", [])
    generation_queue["session_id"] = data.get("session_id")
    generation_queue["status"]     = "queued"
    return {"status": "queued", "total": len(generation_queue["chunks"])}


@app.post("/api/ai/complete")
async def mark_ai_complete(request: Request):
    """Called by mcp_server.py when Claude Desktop finishes generation."""
    generation_queue["status"] = "complete"
    return {"status": "complete"}


@app.get("/api/ai/status")
def get_ai_status():
    """React UI polls this to check if Claude AI generation is done."""
    return {
        "status":   generation_queue["status"],
        "has_data": bool(mcp_results_store.get("test_cases")),
    }


# ── Serve React frontend ─────────────────────────────────────────────────────
# When frozen: check for external frontend/dist next to the EXE first.
# This lets you update the frontend WITHOUT rebuilding the EXE:
#   1. npm run build          2. robocopy frontend\dist dist\frontend\dist /E /IS
#   3. Restart EXE            — changes visible immediately
if getattr(sys, "frozen", False):
    _exe_dir = Path(sys.executable).parent
    _ext     = _exe_dir / "frontend" / "dist"
    _DIST    = _ext if _ext.exists() else Path(sys._MEIPASS) / "frontend" / "dist"
else:
    _DIST = BASE_DIR / "frontend" / "dist"

if _DIST.exists():
    app.mount("/assets", StaticFiles(directory=str(_DIST / "assets")), name="assets")

    @app.get("/", include_in_schema=False)
    async def serve_index():
        return FileResponse(str(_DIST / "index.html"))

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str):
        file_path = _DIST / full_path
        if file_path.exists() and file_path.is_file():
            return FileResponse(str(file_path))
        return FileResponse(str(_DIST / "index.html"))


# ── Entry point ───────────────────────────────────────────────────────────────
def _open_browser():
    import time
    time.sleep(2)
    webbrowser.open("http://localhost:8000")



def _extract_req_content(req_id: str, full_content: str) -> str:
    """Extract only the text block belonging to req_id from combined content."""
    import re
    escaped = re.escape(req_id)
    start_m = re.search(rf'(?:^|\n)\s*{escaped}\b', full_content, re.IGNORECASE)
    if not start_m:
        return full_content
    start = start_m.start()
    next_req = re.search(
        r'\n\s*(?:[A-Z][A-Z0-9]*[_-][A-Z0-9][A-Z0-9_-]{1,40})(?:\s*:|\s+[Tt]he|\s+shall)',
        full_content[start + len(req_id):], re.IGNORECASE
    )
    if next_req:
        end = start + len(req_id) + next_req.start()
        return full_content[start:end].strip()
    return full_content[start:].strip()

def _find_free_port(preferred: int = 8000) -> int:
    """Return preferred port if free, otherwise find the next available one."""
    import socket
    for port in range(preferred, preferred + 20):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("127.0.0.1", port))
                return port
        except OSError:
            continue
    raise RuntimeError("No free port found in range 8000-8019")


if __name__ == "__main__":
    import uvicorn

    port = _find_free_port(8000)

    # Update browser open URL with the actual port
    def _open_browser_port():
        import time
        time.sleep(2)
        webbrowser.open(f"http://localhost:{port}")

    log_cfg = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "fmt": "%(asctime)s %(levelname)s %(message)s",
                "use_colors": False,
            }
        },
        "handlers": {
            "default": {
                "formatter": "default",
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
            }
        },
        "loggers": {
            "uvicorn": {"handlers": ["default"], "level": "WARNING"},
            "uvicorn.error": {"level": "WARNING"},
            "uvicorn.access": {"handlers": ["default"], "level": "WARNING"},
        },
    }

    threading.Thread(target=_open_browser_port, daemon=True).start()
    uvicorn.run(app, host="127.0.0.1", port=port, log_config=log_cfg)