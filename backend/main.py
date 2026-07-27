import json
import logging
import subprocess
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
from typing import Dict, Any, Optional

import asyncio

from fastapi import FastAPI, UploadFile, File, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
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
import doc_cache
from output_validator   import validate_test_cases
from test_case_generator import generate_all, is_spacy_available
from output_generator import generate_excel, generate_docx, compute_gui_display_fields

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

# ─── WEBSOCKET STATUS LAYER ───────────────────────────────────────────────────
# Pushes processing-status events, clarification questions, and final results to
# the React UI in real time. Replaces the old 3s-poll pattern for these events;
# /api/mcp/latest and /api/tokens/usage are left in place as a fallback.
class ConnectionManager:
    def __init__(self):
        self.active: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.append(ws)

    def disconnect(self, ws: WebSocket):
        if ws in self.active:
            self.active.remove(ws)

    async def broadcast(self, message: dict):
        dead = []
        for ws in self.active:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


manager = ConnectionManager()


async def _emit(event_type: str, **payload):
    """Append to the activity log and push to every connected GUI client.
    Every event is stamped with request_id = the current session_id, so the
    GUI (and anyone inspecting the log) can tell which run an event belongs
    to even if a second run starts before the first one's events finish
    displaying."""
    entry = {
        "type": event_type,
        "ts": datetime.now().strftime("%H:%M:%S"),
        "request_id": generation_queue.get("session_id"),
        **payload,
    }
    generation_queue.setdefault("activity_log", []).append(entry)
    generation_queue["activity_log"] = generation_queue["activity_log"][-100:]  # cap
    await manager.broadcast(entry)


@app.websocket("/ws/status")
async def ws_status(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        # Replay recent history so a client that connects mid-run isn't blind.
        for entry in generation_queue.get("activity_log", [])[-20:]:
            await websocket.send_json(entry)
        while True:
            # We don't expect the GUI to push data over this socket except a
            # ping; clarification answers go through the plain HTTP endpoint
            # below so they're logged/validated the same way any POST is.
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)


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

def _ingest_with_cache(text: str, chunk_size_words: int):
    """
    Wraps ingest_document() with a persistent content-hash cache so an
    identical document (same text + same chunk size) is never re-ingested.
    Returns (chunks, text_hash, was_cached).
    """
    text_hash = doc_cache.hash_text(text)
    cached    = doc_cache.get_cached_chunks(text_hash, chunk_size_words)
    if cached is not None:
        logger.info(f"[CACHE HIT] ingest — text_hash={text_hash[:12]}…, skipped ingest_document ({len(cached)} chunks reused)")
        return cached, text_hash, True

    chunks = ingest_document(text, chunk_size_words)
    doc_cache.set_cached_chunks(text_hash, chunk_size_words, chunks)
    return chunks, text_hash, False


def _estimate_tokens(text: str) -> int:
    """Rough token estimate using ~4 chars/token heuristic (Claude-family average)."""
    return max(1, len(text) // 4)


generation_queue: Dict[str, Any] = {
    "chunks":      [],
    "session_id":  None,
    "session_ids": [],       # populated when /api/generate/ai batches multiple documents
    "status":      "idle",   # idle / queued / analysis / generating / clarifying / complete
    "job_status": "RUNNING",  # RUNNING / PAUSED / STOPPED — user-driven Pause/Stop state,
                               # independent of "status" above. This is what the
                               # generation loop (fetch + save endpoints) checks
                               # before doing any further work.
    "activity_log": [],     # rolling log of status events, pushed over /ws/status
    "pending_clarification": None,  # {"question": str, "answer": str|None}
}


# ─── REQUIREMENTS-COVERAGE HELPERS ────────────────────────────────────────────
# "Requirements covered" must reflect how many *in-scope SRS requirements* have
# at least one generated test case — NOT the raw count of distinct req IDs that
# happen to appear on the test cases. Test-case IDs can be blank, placeholder
# ("REQ-001"), or format-variant ("MRJ-MCU-SRS-001" vs "MRJ_MCU_SRS_001"), which
# both over- and under-counts. We canonicalise both sides and intersect.

def _canon_req_id(rid) -> str:
    """Canonical form of a requirement ID: upper-cased, separators unified."""
    return re.sub(r"[\s_\-]+", "_", str(rid or "").upper().strip())


def _coverage(srs_req_ids, test_cases) -> Dict[str, int]:
    """
    Given the authoritative in-scope SRS requirement IDs and the generated test
    cases, return {'requirements_total', 'requirements_covered'}.

    total    = distinct in-scope SRS requirements
    covered  = those SRS requirements that have >=1 test case tracing to them
    """
    srs = {_canon_req_id(r) for r in (srs_req_ids or []) if _canon_req_id(r)}
    tc_ids = {
        _canon_req_id(tc.get("traceability_req_id") if isinstance(tc, dict)
                      else getattr(tc, "traceability_req_id", ""))
        for tc in (test_cases or [])
    }
    tc_ids.discard("")
    if srs:
        return {"requirements_total": len(srs),
                "requirements_covered": len(srs & tc_ids)}
    # No authoritative SRS set available (e.g. queue empty): fall back to the
    # distinct traceable IDs on the test cases so the card still shows something.
    return {"requirements_total": len(tc_ids),
            "requirements_covered": len(tc_ids)}


def _tc_identity(tc) -> str:
    """Stable identity for a test case, used to dedupe when batches are merged.

    Prefers the explicit IDs the generator assigns. Falls back to a content
    hash so that even ID-less rows are not silently collapsed into one another.
    """
    if not isinstance(tc, dict):
        return "obj:" + str(id(tc))
    tcid = str(tc.get("test_case_id") or "").strip()
    scid = str(tc.get("scenario_id") or "").strip()
    rid  = _canon_req_id(tc.get("traceability_req_id"))
    if tcid or scid:
        return f"{rid}|{tcid}|{scid}"
    # No usable IDs — hash the whole row so distinct content stays distinct.
    import hashlib
    blob = json.dumps(tc, sort_keys=True, default=str)
    return "hash:" + hashlib.md5(blob.encode("utf-8")).hexdigest()


def _merge_test_cases(existing, incoming) -> list:
    """Append incoming test cases to existing, dropping exact duplicates.

    Order-preserving: existing rows keep their position, genuinely new rows are
    appended in arrival order. This is what lets multiple batches accumulate
    regardless of how (or how often) the generator saves them.
    """
    merged = list(existing or [])
    seen   = {_tc_identity(tc) for tc in merged}
    for tc in (incoming or []):
        ident = _tc_identity(tc)
        if ident in seen:
            continue
        seen.add(ident)
        merged.append(tc)
    return merged


# ─── GUI DISPLAY FIELD ATTACHMENT ─────────────────────────────────────────────
# mcp_results_store holds plain dicts (not TestCase objects — see
# output_validator.ValidationReport.valid_test_cases), and both the
# websocket "result" event and GET /api/mcp/latest send those dicts straight
# to the GUI as-is. The GUI must not re-derive Test Details Description (or
# the other narrative columns) itself — that duplicate JS logic in
# TCTable.jsx/ResultsTable.jsx is what drifted from the Excel/Word export in
# the first place. Instead, attach the backend-computed text to the dict
# here, right before it is stored/broadcast, using the exact same functions
# generate_excel/generate_docx use.
_TC_DEFAULTS = {
    "traceability_req_id": "", "test_case_id": "", "scenario_id": "",
    "priority": "P2", "objective": "", "preconditions": [],
    "test_steps": [], "inputs": [], "design_methodology": "Equivalence Partitioning",
    "dependent_test_cases": "None", "expected_outcome": "",
    "test_environment": "Dev", "remarks": "", "module": "General",
    "requirement_type": "functional", "scenario_type": "normal",
    "testing_type": "verification",
}

def _attach_display_fields(raw: dict, siblings: Optional[list] = None) -> dict:
    """Computes test_details_description (+ the other display columns) for a
    raw MCP test-case dict and merges them in-place. Never drops or
    overwrites the caller's original fields — only adds the derived ones.

    `siblings` — TestCase objects for every test case in the same batch —
    lets MC/DC (boundary) rows identify which signal is actually being
    isolated in this specific row instead of always naming the first
    declared input(s); see output_generator._description_signal_names.
    """
    from models import TestCase as _TestCase
    merged = {**_TC_DEFAULTS, **{k: v for k, v in raw.items() if k in _TC_DEFAULTS}}
    try:
        tc_obj = _TestCase(**merged)
        raw.update(compute_gui_display_fields(tc_obj, siblings=siblings))
    except Exception:
        logger.warning(
            f"Could not compute GUI display fields for "
            f"{raw.get('test_case_id', '?')}: {traceback.format_exc()}"
        )
    return raw


def _attach_display_fields_all(test_cases: list) -> list:
    """Builds a TestCase object for every raw dict once (so each row can see
    its siblings for MC/DC signal detection), then attaches the computed
    display fields to each original dict."""
    from models import TestCase as _TestCase
    tc_objs = []
    for raw in test_cases:
        merged = {**_TC_DEFAULTS, **{k: v for k, v in raw.items() if k in _TC_DEFAULTS}}
        try:
            tc_objs.append(_TestCase(**merged))
        except Exception:
            tc_objs.append(None)
    for raw, tc_obj in zip(test_cases, tc_objs):
        if tc_obj is None:
            continue
        siblings = [o for o in tc_objs if o is not None]
        try:
            raw.update(compute_gui_display_fields(tc_obj, siblings=siblings))
        except Exception:
            logger.warning(
                f"Could not compute GUI display fields for "
                f"{raw.get('test_case_id', '?')}: {traceback.format_exc()}"
            )
    return test_cases


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

@app.get("/api/debug/cache")
def debug_cache():
    """Shows how many documents/chunk-sets are currently cached on disk."""
    return doc_cache.cache_stats()


@app.post("/api/debug/cache/clear")
def debug_cache_clear():
    """Wipes the on-disk text/chunk caches. Use after a genuine ingestion-logic
    change if you forgot to bump doc_cache.CACHE_FORMAT_VERSION."""
    doc_cache.clear_cache()
    return {"status": "cleared"}


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
    allowed = {".pdf", ".docx", ".doc", ".xlsx", ".xls", ".txt"}
    suffix  = f".{file.filename.lower().rsplit('.', 1)[-1]}" if "." in file.filename else ""
    if suffix not in allowed:
        _error(
            "Unsupported file type",
            "parsing",
            f"Received: {suffix}",
            "Upload a .pdf, .docx, .xlsx, or .txt file",
            400,
        )

    raw_bytes = await file.read()
    file_hash = doc_cache.hash_bytes(raw_bytes)

    # ── Content-hash cache lookup: skip re-parsing an identical file ────────
    cached_text = doc_cache.get_cached_text(file_hash)
    from_cache  = cached_text is not None

    if from_cache:
        text = cached_text
        logger.info(f"[CACHE HIT] upload — {file.filename} matches file_hash={file_hash[:12]}…, skipped parse_file")
    else:
        try:
            text = parse_file(file.filename, raw_bytes)
        except Exception:
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

        doc_cache.set_cached_text(file_hash, file.filename, text)

    session_id = str(uuid.uuid4())
    sessions[session_id] = {
        "filename":   file.filename,
        "doc_type":   doc_type,
        "text":       text,
        "file_hash":  file_hash,
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

    # Count occurrences of each requirement ID to detect duplicates
    from collections import Counter
    rid_counts = Counter(
        c.requirement_ids[0] for c in chunks if c.requirement_ids
    )

    # Preserve document order — include EVERY occurrence with plain ID
    req_id_entries = []   # list of {id, count, duplicate} for frontend
    for c in chunks:
        rid = c.requirement_ids[0] if c.requirement_ids else None
        if rid:
            total = rid_counts[rid]
            # Always use the plain ID — frontend handles display
            req_ids.append(rid)
            req_id_entries.append({
                "id":        rid,
                "count":     total,
                "duplicate": total > 1,
            })
        mod = c.module or "General"
        if mod not in seen_m:
            seen_m.add(mod)
            modules.append(mod)

    dup_entries = [e for e in req_id_entries if e["duplicate"]]
    return {
        "requirement_ids": req_ids,
        "modules":         modules,
        "req_id_entries":  req_id_entries,
        "duplicate_count": len(set(e["id"] for e in dup_entries)),
        "duplicates":      dup_entries,
    }


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
        chunks, _text_hash, _was_cached = _ingest_with_cache(text, CHUNK_SIZE_WORDS)

        # ── Requirement ID prefix filter (rule-based) ────────────────────────
        req_prefixes = getattr(request, "req_prefixes", None) or []
        if req_prefixes:
            prefixes = [p.strip() for p in req_prefixes if p.strip()]
            if prefixes:
                before_pf = len(chunks)
                chunks = [c for c in chunks
                          if c.requirement_ids and
                          any(c.requirement_ids[0].startswith(px) for px in prefixes)]
                logger.info(f"[PREFIX/NLP] {prefixes} → {before_pf} → {len(chunks)} chunks")
        # ─────────────────────────────────────────────────────────────────────

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
        elif (request.selected_modules or request.selected_module) and \
             request.selected_module != "__all__":
            # Support both single module and multi-module selection
            mods = set(request.selected_modules or [])
            if request.selected_module and request.selected_module not in mods:
                mods.add(request.selected_module)
            before = len(chunks)
            chunks = [c for c in chunks if (c.module or "General") in mods]
            logger.info(f"[SCOPE] module filter {mods} → {before} → {len(chunks)} chunks")
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
            "rp6": rp.rp6,
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

        # Attach Test Details Description etc. so the GUI (if it ever renders
        # rule-engine results directly) shows the same text as the Excel/Word
        # export instead of re-deriving it with stale JS logic.
        for tc in test_cases:
            for field_name, value in compute_gui_display_fields(tc, siblings=test_cases).items():
                setattr(tc, field_name, value)

        sessions[request.session_id]["chunks"]     = chunks
        sessions[request.session_id]["test_cases"] = test_cases
        sessions[request.session_id]["removed"]    = removed

        # In-scope SRS requirements = PRIMARY requirement ID per chunk only.
        # Using all requirement_ids inflates the count with cross-reference
        # labels (e.g. "B4", "B5") that are not real requirements.
        srs_req_ids = {
            c.requirement_ids[0] for c in chunks
            if c.requirement_ids and c.requirement_ids[0]
        }
        cov = _coverage(srs_req_ids, test_cases)

        summary = GenerateSummary(
            total               = len(test_cases),
            by_module           = dict(Counter(tc.module           for tc in test_cases)),
            by_requirement_type = dict(Counter(tc.requirement_type for tc in test_cases)),
            by_scenario_type    = dict(Counter(tc.scenario_type    for tc in test_cases)),
            by_testing_type     = dict(Counter(tc.testing_type     for tc in test_cases)),
            by_priority         = dict(Counter(tc.priority         for tc in test_cases)),
            duplicates_removed  = removed,
            requirements_total   = cov["requirements_total"],
            requirements_covered = cov["requirements_covered"],
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

# ── Open Claude Desktop endpoint ─────────────────────────────────────────────
@app.post("/api/open-claude")
async def open_claude(request: Request):
    """
    Brings Claude Desktop to front using PowerShell AppActivate, and pastes
    the generated prompt into a new chat.

    The prompt is written to a temp file and the clipboard is set by the
    PowerShell script itself (Set-Clipboard) immediately before the paste —
    NOT by the browser's navigator.clipboard.writeText. Relying on the browser
    call left a race/silent-failure gap (focus-stealing on the click,
    permissions-policy denial, etc. would fail the write with no visible
    error, so ^v would paste stale or empty clipboard content even though the
    window activation and keystrokes all "worked"). Setting the clipboard
    inside the same synchronous script that does the paste removes that race
    entirely.
    """
    import pathlib, tempfile, os

    try:
        data = await request.json()
    except Exception:
        data = {}
    prompt_text = data.get("prompt", "") or ""

    # Write the prompt to its own temp file — safer than trying to escape
    # arbitrary prompt content (quotes, backticks, newlines) into a PS string.
    prompt_file = tempfile.NamedTemporaryFile(
        mode='w', suffix='.txt', delete=False, encoding='utf-8'
    )
    prompt_file.write(prompt_text)
    prompt_file.close()
    prompt_path = prompt_file.name

    ps_script = """
# Set the clipboard from the prompt file FIRST, synchronously, so there is
# no race with the paste below.
$promptText = Get-Content -Raw -Encoding UTF8 -Path '__PROMPT_PATH__'
if ($promptText) { Set-Clipboard -Value $promptText }

$proc = Get-Process -Name 'claude' -ErrorAction SilentlyContinue | Where-Object {$_.MainWindowTitle -eq 'Claude'} | Select-Object -First 1
if ($proc) {
    $wshell = New-Object -ComObject WScript.Shell
    # Bring Claude to front
    $wshell.AppActivate($proc.Id)
    Start-Sleep -Milliseconds 800
    # Open a new chat
    $wshell.SendKeys('^n')
    Start-Sleep -Milliseconds 2000
    # Bring focus again — new chat may shift focus
    $wshell.AppActivate('Claude')
    Start-Sleep -Milliseconds 500
    # Paste the clipboard prompt
    $wshell.SendKeys('^v')
    Start-Sleep -Milliseconds 800
    # Press Enter to start generation
    $wshell.SendKeys('~')
} else {
    # Claude not running — launch it, wait for load, then paste
    explorer.exe 'shell:AppsFolder\Claude_pzs8sxrjxfjjc!Claude'
    Start-Sleep -Seconds 6
    $wshell2 = New-Object -ComObject WScript.Shell
    $wshell2.AppActivate('Claude')
    Start-Sleep -Milliseconds 1000
    $wshell2.SendKeys('^n')
    Start-Sleep -Milliseconds 2000
    $wshell2.AppActivate('Claude')
    Start-Sleep -Milliseconds 500
    $wshell2.SendKeys('^v')
    Start-Sleep -Milliseconds 800
    $wshell2.SendKeys('~')
}

Remove-Item -Path '__PROMPT_PATH__' -ErrorAction SilentlyContinue
""".replace('__PROMPT_PATH__', prompt_path)

    try:
        # Write PS1 to temp file
        tmp = tempfile.NamedTemporaryFile(
            mode='w', suffix='.ps1', delete=False, encoding='utf-8'
        )
        tmp.write(ps_script)
        tmp.close()

        # Run with powershell.exe directly — preserves desktop session
        subprocess.Popen(
            [
                "powershell.exe",
                "-NoProfile",
                "-WindowStyle", "Hidden",
                "-ExecutionPolicy", "Bypass",
                "-File", tmp.name
            ],
            shell=False
        )
        logger.info(f"[OPEN-CLAUDE] PS1 launched: {tmp.name} | prompt_chars={len(prompt_text)}")
        return {"status": "launched", "method": "powershell_ps1"}

    except Exception as e:
        logger.warning(f"[OPEN-CLAUDE] PS1 failed: {e}")
        return {"status": "error", "message": str(e)}
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

        # ── Multi-document support ─────────────────────────────────────────
        # Accept EITHER a single "session_id" (existing behaviour, unchanged)
        # OR a "session_ids" list, to batch requirements across every document
        # queued so far in one pass. Falls back to [session_id] when absent.
        session_ids = data.get("session_ids") or ([session_id] if session_id else [])
        session_ids = [sid for sid in session_ids if sid]

        # ── DEBUG: store and log incoming payload ─────────────────────────
        _last_ai_request.clear()
        _last_ai_request.update({
            "keys":                   list(data.keys()),
            "req_prefixes":           data.get("req_prefixes"),
            "session_ids":            session_ids,
            "selected_module":        data.get("selected_module"),
            "selected_modules_count": len(data.get("selected_modules") or []),
            "selected_modules_sample":(data.get("selected_modules") or [])[:3],
        })
        logger.info(
            f"[AI-ENDPOINT] incoming keys={list(data.keys())} | "
            f"req_prefixes={data.get('req_prefixes')!r} | "
            f"selected_req_ids={data.get('selected_req_ids')!r} | "
            f"session_ids={session_ids!r}"
        )
        # ─────────────────────────────────────────────────────────────────

        if not session_ids:
            raise HTTPException(status_code=400, detail="session_id or session_ids is required")

        missing = [sid for sid in session_ids if sid not in sessions]
        if missing:
            raise HTTPException(status_code=404, detail=f"Session(s) not found: {missing}. Upload the file(s) first.")

        # ── Optional ICD/supporting context, applied against the first
        # session in the batch (kept for backward compatibility with the
        # single-document ICD-merge flow; multi-doc batching does not
        # currently fan this out to every session). ──────────────────────
        icd_text = ""
        icd_session_id = data.get("icd_session_id")
        if icd_session_id and icd_session_id in sessions:
            icd_text = sessions[icd_session_id].get("text", "")

        supporting_text = ""
        supporting_session_id = data.get("supporting_session_id")
        if supporting_session_id and supporting_session_id in sessions:
            supporting_text = sessions[supporting_session_id].get("text", "")

        if icd_text or supporting_text:
            logger.info(
                f"[AI-ENDPOINT] ICD/supporting context attached "
                f"(icd={bool(icd_text)}, supporting={bool(supporting_text)}) — "
                f"note: informational only, not yet merged into ingestion for "
                f"multi-document batches"
            )

        # ── Scope filter params (same for every document in the batch) ──────
        selected_req_ids = data.get("selected_req_ids")   # list or None
        selected_module  = data.get("selected_module")    # str or None
        selected_modules = data.get("selected_modules")   # list or None
        req_prefixes     = [p.strip() for p in (data.get("req_prefixes") or []) if p.strip()]

        chunk_data   = []   # merged, across every document in session_ids
        all_chunks   = {}   # session_id -> chunks, so each session keeps its own for reference
        cache_hits   = 0

        for sid in session_ids:
            session  = sessions[sid]
            text     = session["text"]
            filename = session.get("filename", sid)

            # Ingest SRS ONLY (cached by content hash — identical documents,
            # even across different upload sessions, are never re-ingested).
            # ICD/supporting text is deliberately excluded here — it contains
            # identifiers that confuse the parser and create phantom chunks.
            chunks, _text_hash, was_cached = _ingest_with_cache(text, CHUNK_SIZE_WORDS)
            if was_cached:
                cache_hits += 1

            # ── Requirement ID prefix filter ─────────────────────────────
            if req_prefixes:
                before_pf = len(chunks)
                chunks = [c for c in chunks
                          if c.requirement_ids and
                          any(c.requirement_ids[0].startswith(px) for px in req_prefixes)]
                logger.info(f"[PREFIX/AI] {filename} — {req_prefixes} → {before_pf} → {len(chunks)} chunks")

            if selected_req_ids is not None:
                keep   = set(selected_req_ids)
                before = len(chunks)
                chunks = [c for c in chunks
                          if any(rid in keep for rid in (c.requirement_ids or []))]
                logger.info(f"[SCOPE/AI] {filename} — req filter → {before} → {len(chunks)} chunks")
            elif (selected_modules or selected_module) and selected_module != "__all__":
                mods = set(selected_modules or [])
                if selected_module and selected_module not in mods:
                    mods.add(selected_module)
                before = len(chunks)
                chunks = [c for c in chunks if (c.module or "General") in mods]
                logger.info(f"[SCOPE/AI] {filename} — module filter {mods} → {before} → {len(chunks)} chunks")
            else:
                logger.info(f"[SCOPE/AI] {filename} — no filter — queuing all {len(chunks)} chunks")

            all_chunks[sid] = chunks
            sessions[sid]["chunks"] = chunks

            # Expand: one entry per requirement ID so Claude gets context for
            # EVERY requirement even when multiple reqs share the same chunk.
            for c in chunks:
                req_id = c.requirement_ids[0] if c.requirement_ids else "REQ-001"
                chunk_data.append({
                    "requirement_id":   req_id,
                    "content":          c.content,
                    "module":           c.module or "General",
                    "requirement_type": c.requirement_type,
                    "source_session_id": sid,
                    "source_filename":   filename,
                })

        logger.info(
            f"[AI-ENDPOINT] merged {len(session_ids)} document(s) → "
            f"{len(chunk_data)} requirement(s) queued | cache_hits={cache_hits}/{len(session_ids)}"
        )

        if not chunk_data:
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "No requirements found",
                    "suggestion": "Verify SRS language uses shall/must/should.",
                },
            )

        # Queue the merged set for Claude AI. get_generated_test_cases's
        # batch_index/batch_size in mcp_server.py slices across this combined
        # list, so a single batching pass now spans every document queued.
        generation_queue["chunks"]      = chunk_data
        generation_queue["session_id"]  = session_ids[0]
        generation_queue["session_ids"] = session_ids
        generation_queue["status"]      = "queued"
        generation_queue["job_status"]  = "RUNNING"
        generation_queue["activity_log"] = []
        generation_queue["pending_clarification"] = None
        generation_queue["rp6"]         = bool(data.get("review_points", {}).get("rp6", False))

        # Clear any stale MCP results so the UI does not show old data.
        # This is the single per-run reset boundary — both the visible store and
        # the in-flight chunk buffer are cleared so a new generation starts clean
        # and batches only accumulate within one run.
        global _chunk_buffer
        _chunk_buffer = []
        mcp_results_store["test_cases"] = []
        mcp_results_store["summary"]    = None
        mcp_results_store["timestamp"]  = None

        logger.info(
            f"AI generation queued: {len(chunk_data)} chunks "
            f"(sessions={session_ids})"
        )
        await _emit("status", stage="Request Submitted",
                    detail=f"{len(chunk_data)} requirements queued")
        return {
            "status":       "queued",
            "total_chunks": len(chunk_data),
            "session_id":   session_ids[0],
            "session_ids":  session_ids,
            "request_id":   session_ids[0],
        }

    except HTTPException as e:
        await _emit("error", message=str(e.detail))
        raise
    except Exception as e:
        logger.error(f"AI queue error: {traceback.format_exc()}")
        await _emit("error", message=f"Generation failed to start: {e}")
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
    raw_tcs = [_normalise_mcp_tc(tc) for tc in data.get("test_cases", [])]
    queued_req_ids = {
        c.get("requirement_id") for c in generation_queue.get("chunks", [])
        if c.get("requirement_id")
    }
    report = validate_test_cases(raw_tcs, valid_req_ids=queued_req_ids or None)
    _last_validation_report.update(report.summary())
    validated_tcs = report.valid_test_cases
    # Accumulate across saves (see save_finalise) instead of overwriting.
    validated_tcs = _merge_test_cases(mcp_results_store.get("test_cases"), validated_tcs)
    # Attach Test Details Description etc. so the GUI shows the same text as
    # the Excel/Word export instead of re-deriving it with stale JS logic.
    validated_tcs = _attach_display_fields_all(validated_tcs)
    _mcp_summary = dict(data.get("summary", {}) or {})
    cov = _coverage(queued_req_ids, validated_tcs)
    _mcp_summary["requirements_total"]   = cov["requirements_total"]
    _mcp_summary["requirements_covered"] = cov["requirements_covered"]
    mcp_results_store["test_cases"] = validated_tcs
    mcp_results_store["summary"]    = _mcp_summary
    mcp_results_store["timestamp"]  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    generation_queue["status"]      = "complete"
    logger.info(
        f"MCP results saved: {len(validated_tcs)} test cases "
        f"(fixed={report.auto_fixed}, dropped={report.dropped})"
    )
    await _emit("status", stage="Completion",
                detail=f"{len(validated_tcs)} test cases saved")
    await _emit("result", test_cases=validated_tcs, summary=_mcp_summary)
    return {"status": "saved", "total": len(validated_tcs),
            "validation": _last_validation_report}


# ── Chunked save endpoints for large test case batches ───────────────────────
# mcp_server.py calls these instead of /api/mcp/save when is_partial is used,
# so each MCP call stays well under the 1MB payload limit.
_chunk_buffer: list = []

def _check_job_status():
    """Raises if Job Status is PAUSED or STOPPED (set via /api/job/pause|stop).
    Called from save_chunk and save_finalise — the generation loop's actual
    check-before-processing points. Claude Desktop runs the multi-batch loop
    autonomously inside its own chat turn (seeded by one upfront prompt from
    /api/open-claude); the backend has no channel to reach into that turn and
    interrupt it directly. What it CAN guarantee is that nothing gets
    persisted once Job Status leaves RUNNING, and that the next tool call
    Claude makes gets a plain-language instruction to stop or hold."""
    job_status = generation_queue.get("job_status", "RUNNING")
    if job_status == "STOPPED":
        raise HTTPException(status_code=409, detail={
            "job_status": "STOPPED",
            "message": ("Generation was stopped by the user. This batch was NOT saved. "
                        "Do not retry it, and make no further tool calls for this run."),
        })
    if job_status == "PAUSED":
        raise HTTPException(status_code=409, detail={
            "job_status": "PAUSED",
            "message": ("Generation is paused by the user. This batch was NOT saved. "
                        "Hold this exact batch and retry the same save once the user "
                        "resumes — do not move on to the next batch in the meantime."),
        })


@app.post("/api/mcp/save_chunk")
async def save_chunk(request: Request):
    """Receives one batch of test cases. Buffers them in memory.
    Called once per batch. Use is_last=True on the final batch."""
    global _chunk_buffer
    _check_job_status()
    data = await request.json()
    chunk = [_normalise_mcp_tc(tc) for tc in data.get("test_cases", [])]
    is_last = data.get("is_last", False)
    _chunk_buffer.extend(chunk)
    logger.info(f"[CHUNK SAVE] +{len(chunk)} test cases | buffer_total={len(_chunk_buffer)} | is_last={is_last}")
    generation_queue["status"] = "generating"
    await _emit("status", stage="Test Case Generation",
                detail=f"+{len(chunk)} test cases, running total {len(_chunk_buffer)}")
    return {"status": "chunk_received", "buffer_total": len(_chunk_buffer), "is_last": is_last}


def _finalise_test_cases(test_cases: list) -> dict:
    """Shared finalisation logic: validate, merge into the accumulated store,
    build the summary. Used by both /api/mcp/save_finalise (normal end-of-run,
    Claude-driven) and /api/generation/stop (user-forced stop, salvaging
    whatever was buffered so it isn't lost)."""
    from collections import Counter

    queued_req_ids = {
        c.get("requirement_id") for c in generation_queue.get("chunks", [])
        if c.get("requirement_id")
    }
    report = validate_test_cases(test_cases, valid_req_ids=queued_req_ids or None)
    _last_validation_report.update(report.summary())
    test_cases = report.valid_test_cases

    if report.dropped > 0:
        logger.warning(
            f"[VALIDATION] Dropped {report.dropped} malformed test cases. "
            f"Errors: {report.summary()['error_count']}"
        )

    # Accumulate across batches: merge this finalised batch into whatever is
    # already stored for this run rather than overwriting it.
    test_cases = _merge_test_cases(mcp_results_store.get("test_cases"), test_cases)
    # Attach Test Details Description etc. so the GUI shows the same text as
    # the Excel/Word export instead of re-deriving it with stale JS logic.
    test_cases = _attach_display_fields_all(test_cases)

    cov = _coverage(queued_req_ids, test_cases)
    summary = {
        "total":               len(test_cases),
        "duplicates_removed":  0,
        "requirements_total":   cov["requirements_total"],
        "requirements_covered": cov["requirements_covered"],
        "by_module":           dict(Counter(tc.get("module", "General")            for tc in test_cases)),
        "by_requirement_type": dict(Counter(tc.get("requirement_type", "functional") for tc in test_cases)),
        "by_scenario_type":    dict(Counter(tc.get("scenario_type", "normal")        for tc in test_cases)),
        "by_testing_type":     dict(Counter(tc.get("testing_type", "verification")   for tc in test_cases)),
        "by_priority":         dict(Counter(tc.get("priority", "P1")                 for tc in test_cases)),
        "validation":          _last_validation_report,
    }

    mcp_results_store["test_cases"] = test_cases
    mcp_results_store["summary"]    = summary
    mcp_results_store["timestamp"]  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return summary


@app.post("/api/mcp/save_finalise")
async def save_finalise():
    """Merges all buffered chunks into mcp_results_store and completes the queue.
    Called once after the final batch's save_chunk."""
    global _chunk_buffer
    _check_job_status()

    test_cases = list(_chunk_buffer)
    _chunk_buffer = []

    if not test_cases:
        await _emit("error", message="save_finalise called with no chunks buffered — call save_chunk first")
        raise HTTPException(status_code=400, detail="No chunks buffered. Send chunks via save_chunk first.")

    summary = _finalise_test_cases(test_cases)
    generation_queue["status"] = "complete"

    logger.info(f"[FINALISE] Saved {summary['total']} validated test cases")
    await _emit("status", stage="Completion",
                detail=f"{summary['total']} test cases finalised")
    await _emit("result", test_cases=mcp_results_store["test_cases"], summary=summary)
    return {"status": "finalised", "total": summary["total"],
            "summary": summary, "validation": _last_validation_report}


# ─── JOB CONTROL (pause / resume / stop) ──────────────────────────────────────
# User Clicks Stop → GUI → POST /api/job/stop → Backend sets Job Status = STOPPED
# → the generation loop's check points (save_chunk / save_finalise, plus the
# /api/ai/queue fetch below) see it on their next call → stop further processing.
#
# The backend can't reach into Claude's live turn and interrupt an in-flight
# tool call — what it CAN do reliably is (a) refuse to hand out further batches
# or accept further saves once Job Status leaves RUNNING, and (b) tell Claude
# plainly, in the tool result itself, to stop or hold. Claude will generally
# comply on its *next* tool call because the instruction is in the data it
# just read — but a currently-executing tool call (e.g. mid-generation before
# it calls save_enhanced_test_cases) will still finish that one step; this is
# a limit of the MCP execution layer, not something a backend flag can reach
# into. Stop salvages whatever was already buffered so it isn't lost.

@app.get("/api/job/status")
async def get_job_status():
    """Current Job Status, for the GUI to reconcile on load/reconnect
    (the websocket 'control' event is the live path; this is the pull path)."""
    return {
        "job_status": generation_queue.get("job_status", "RUNNING"),
        "stage":      generation_queue.get("status"),
    }


@app.post("/api/job/pause")
async def pause_job():
    if generation_queue.get("job_status") == "STOPPED":
        raise HTTPException(status_code=400, detail="Job already stopped — cannot pause.")
    generation_queue["job_status"] = "PAUSED"
    await _emit("control", state="paused")
    logger.info("[JOB] Status -> PAUSED (user).")
    return {"job_status": "PAUSED"}


@app.post("/api/job/resume")
async def resume_job():
    if generation_queue.get("job_status") == "STOPPED":
        raise HTTPException(status_code=400, detail="Cannot resume a stopped job — start a new generation.")
    generation_queue["job_status"] = "RUNNING"
    await _emit("control", state="running")
    logger.info("[JOB] Status -> RUNNING (resumed by user).")
    return {"job_status": "RUNNING"}


@app.post("/api/job/stop")
async def stop_job():
    """Job Status = STOPPED. Any chunks already buffered (saved via save_chunk
    but not yet finalised) are salvaged into mcp_results_store so partial
    results stay available through Load Results — nothing already generated
    is thrown away."""
    global _chunk_buffer
    generation_queue["job_status"] = "STOPPED"

    salvaged = 0
    if _chunk_buffer:
        test_cases = list(_chunk_buffer)
        _chunk_buffer = []
        summary = _finalise_test_cases(test_cases)
        salvaged = summary["total"]
        generation_queue["status"] = "complete"
        await _emit("status", stage="Completion",
                    detail=f"Stopped by user — {salvaged} test cases salvaged")
        await _emit("result", test_cases=mcp_results_store["test_cases"], summary=summary)
    else:
        await _emit("status", stage=generation_queue.get("status", "Test Case Generation"),
                    detail="Stopped by user — no test cases had been buffered yet")

    await _emit("control", state="stopped", salvaged=salvaged)
    logger.info(f"[JOB] Status -> STOPPED (user). Salvaged {salvaged} test cases.")
    return {"job_status": "STOPPED", "salvaged_test_cases": salvaged}
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
async def get_ai_queue():
    """Claude Desktop MCP server calls this to get pending requirements.
    This is the fetch-side half of 'Generation Loop Checks Status' — the
    save-side half is _check_job_status() in save_chunk/save_finalise."""
    job_status = generation_queue.get("job_status", "RUNNING")
    if job_status == "STOPPED":
        return {
            "chunks": [], "status": generation_queue["status"], "total": 0,
            "job_status": "STOPPED",
            "message": ("Generation was stopped by the user from the GUI. Do not "
                        "fetch further batches or generate more test cases for this run."),
        }
    if job_status == "PAUSED":
        return {
            "chunks": [], "status": generation_queue["status"], "total": 0,
            "job_status": "PAUSED",
            "message": ("Generation is paused by the user from the GUI. Stop here and "
                        "do not continue — wait for the user to resume before fetching "
                        "further batches."),
        }
    generation_queue["status"] = "analysis"
    await _emit("status", stage="Requirement Analysis",
                detail=f"{len(generation_queue['chunks'])} requirements fetched")
    return {
        "chunks": generation_queue["chunks"],
        "status": generation_queue["status"],
        "total":  len(generation_queue["chunks"]),
        "job_status": "RUNNING",
        "rp6_merge":  generation_queue.get("rp6", False),
    }


# ── Validation report store ───────────────────────────────────────────────────
_last_validation_report: dict = {}

@app.get("/api/debug/claude-launch")
async def debug_claude_launch():
    """Test endpoint - shows exactly what happens when we try to launch Claude."""
    import sys, os
    APP_ID = "Claude_pzs8sxrjxfjjc!Claude"
    results = {}

    # Test 1: schtasks create
    try:
        cmd = f'explorer.exe "shell:AppsFolder\\{APP_ID}"'
        r1 = subprocess.run(
            ["schtasks", "/create", "/tn", "OpenClaudeTest", "/tr", cmd,
             "/sc", "ONCE", "/st", "00:00", "/f"],
            capture_output=True, text=True, timeout=10
        )
        results["schtasks_create"] = {"rc": r1.returncode, "out": r1.stdout, "err": r1.stderr}
    except Exception as e:
        results["schtasks_create"] = {"error": str(e)}

    # Test 2: schtasks run
    try:
        r2 = subprocess.run(
            ["schtasks", "/run", "/tn", "OpenClaudeTest"],
            capture_output=True, text=True, timeout=10
        )
        results["schtasks_run"] = {"rc": r2.returncode, "out": r2.stdout, "err": r2.stderr}
    except Exception as e:
        results["schtasks_run"] = {"error": str(e)}

    # Test 3: session info
    try:
        r3 = subprocess.run(["query", "session"], capture_output=True, text=True, timeout=5)
        results["sessions"] = r3.stdout
    except Exception as e:
        results["sessions"] = str(e)

    results["pid"] = os.getpid()
    results["user"] = os.environ.get("USERNAME", "unknown")
    results["session_id"] = os.environ.get("SESSIONNAME", "unknown")
    return results

@app.get("/api/validation/report")
async def get_validation_report():
    """Returns the validation report from the last save_finalise call."""
    return _last_validation_report or {"message": "No validation report yet"}

# ─────────────────────────────────────────────────────────────────────────────

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
    generation_queue["session_id"] = data.get("session_id") or str(uuid.uuid4())
    generation_queue["status"]     = "queued"
    generation_queue["job_status"] = "RUNNING"
    generation_queue["activity_log"] = []
    generation_queue["pending_clarification"] = None
    await _emit("status", stage="Request Submitted",
                detail=f"{len(generation_queue['chunks'])} requirements queued")
    return {
        "status": "queued",
        "total": len(generation_queue["chunks"]),
        "request_id": generation_queue["session_id"],
    }


@app.post("/api/ai/complete")
async def mark_ai_complete(request: Request):
    """Called by mcp_server.py when Claude Desktop finishes generation."""
    generation_queue["status"] = "complete"
    await _emit("status", stage="Completion", detail="Generation finished")
    return {"status": "complete"}


@app.get("/api/ai/status")
def get_ai_status():
    """React UI polls this to check if Claude AI generation is done."""
    return {
        "status":   generation_queue["status"],
        "has_data": bool(mcp_results_store.get("test_cases")),
    }


# ── Clarification (blocking) ──────────────────────────────────────────────────
# Claude Desktop never talks to the GUI directly. To surface a mid-generation
# question in the React UI, the MCP tool call that needs an answer blocks here
# — polling this in-memory state — until the GUI posts a response or the
# timeout elapses. From Claude Desktop's side this just looks like one slow
# tool call; the "conversation" is entirely a GUI <-> backend affair.
CLARIFICATION_TIMEOUT_S = 300


@app.post("/api/mcp/clarify")
async def request_clarification(request: Request):
    """Called by mcp_server.py's ask_clarification tool. Blocks until the GUI
    answers or CLARIFICATION_TIMEOUT_S elapses, then returns the answer."""
    data = await request.json()
    question = data.get("question", "").strip()
    options  = data.get("options") or None
    if not question:
        await _emit("error", message="ask_clarification called with an empty question")
        raise HTTPException(status_code=400, detail="question is required")

    generation_queue["status"] = "clarifying"
    generation_queue["pending_clarification"] = {
        "question": question, "options": options, "answer": None,
    }
    await _emit("clarification_question", question=question, options=options)

    waited = 0.0
    poll_interval = 0.5
    while waited < CLARIFICATION_TIMEOUT_S:
        pending = generation_queue.get("pending_clarification")
        if pending and pending.get("answer") is not None:
            answer = pending["answer"]
            generation_queue["pending_clarification"] = None
            generation_queue["status"] = "generating"
            return {"answered": True, "answer": answer}
        await asyncio.sleep(poll_interval)
        waited += poll_interval

    # Timed out — clear the pending question so the GUI stops showing it.
    generation_queue["pending_clarification"] = None
    generation_queue["status"] = "generating"
    await _emit("error", message="Clarification timed out after 5 minutes — Claude will proceed without an answer")
    return {"answered": False, "answer": None}


@app.post("/api/clarify/respond")
async def respond_to_clarification(request: Request):
    """Called by the React UI when the user answers a clarification question."""
    data = await request.json()
    answer = data.get("answer", "").strip()
    pending = generation_queue.get("pending_clarification")
    if not pending:
        await _emit("error", message="Received a clarification answer but nothing is pending")
        raise HTTPException(status_code=409, detail="No clarification is currently pending")
    pending["answer"] = answer
    await _emit("user_response", answer=answer)
    return {"status": "received"}


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