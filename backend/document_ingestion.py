import re
from typing import List, Dict, Optional
from models import DocumentChunk
from constants import MODULE_KEYWORDS, FUNCTIONAL_VERBS, NON_FUNCTIONAL_KEYWORDS


# ─────────────────────────────────────────────────────────────────────────────
#  FLEXIBLE REQUIREMENT ID DETECTION
# ─────────────────────────────────────────────────────────────────────────────

_BULLET_STRIP = re.compile(r'^[\s\-\*\•\►\▶\→\>\|#~=]+')

_FULL_ID = re.compile(
    r'^[\[\(]?'
    r'('
    r'[A-Za-z][A-Za-z0-9_]{0,14}'
    r'(?:[-_][A-Za-z][A-Za-z0-9_]{0,14})*'
    r'[-_.]?'
    r'\d+'
    r'(?:[-_.]\d+)*'
    r')[\]\)]?$',
    re.IGNORECASE,
)

_SECTION_ID = re.compile(r'^(\d+(?:\.\d+)+)$')

_EXPLICIT_LABEL = re.compile(
    r'(?:requirement\s+id|req\.?\s*id|id)\s*[:\-]\s*'
    r'([A-Z][A-Z0-9_\-\.]*\d)',
    re.IGNORECASE,
)

# Bold heading markers injected by file_parser
_MODULE_MARKER = re.compile(r'^\[MODULE:\s*(.+?)\]$', re.IGNORECASE)


def _ids_at_line_start(line: str) -> List[str]:
    m = _EXPLICIT_LABEL.search(line)
    if m:
        return [m.group(1)]

    stripped = _BULLET_STRIP.sub('', line).strip()
    if not stripped:
        return []

    parts     = stripped.split()
    first_tok = parts[0].strip('[]().,;:') if parts else ''
    if not first_tok:
        return []

    m = _FULL_ID.match(first_tok)
    if m:
        c = m.group(1)
        if not c.isdigit():
            return [c]

    m = _SECTION_ID.match(first_tok)
    if m:
        return [m.group(1)]

    if len(parts) >= 2:
        combined = ''.join(parts[:3]).strip('[]().,;:')
        m = _FULL_ID.match(combined)
        if m:
            c = m.group(1)
            if not c.isdigit():
                return [c]

    return []


def _all_ids_in_line(line: str) -> List[str]:
    found = []
    for m in _EXPLICIT_LABEL.finditer(line):
        found.append(m.group(1))
    for token in re.split(r'[\s,;]+', line):
        clean = token.strip('[]().,;:')
        if not clean:
            continue
        m = re.match(
            r'^[\[\(]?'
            r'([A-Za-z][A-Za-z0-9_]{0,14}'
            r'(?:[-_][A-Za-z][A-Za-z0-9_]{0,14})*'
            r'[-_.]?\d+(?:[-_.]\d+)*)[\]\)]?$',
            clean
        )
        if m:
            c = m.group(1)
            if not c.isdigit() and len(c) >= 2:
                found.append(c)
        else:
            sm = _SECTION_ID.match(clean)
            if sm:
                found.append(sm.group(1))
    seen, unique = set(), []
    for x in found:
        key = x.lower()
        if key not in seen:
            seen.add(key)
            unique.append(x)
    return unique


# ─── MODULE DETECTION ─────────────────────────────────────────────────────────

def detect_module_from_heading(text: str) -> Optional[str]:
    """
    Detects a module name from a [MODULE: <text>] marker injected by file_parser.
    Returns None if no marker found.
    """
    m = _MODULE_MARKER.match(text.strip())
    if m:
        return m.group(1).strip()
    return None


def detect_module(text: str) -> str:
    lower = text.lower()
    for module in MODULE_KEYWORDS:
        if module.lower() in lower:
            return module
    return "General"


# ─── REQUIREMENT TYPE CLASSIFICATION ─────────────────────────────────────────

def classify_requirement(text: str) -> str:
    lower = text.lower()
    if any(k in lower for k in NON_FUNCTIONAL_KEYWORDS):
        return "non-functional"
    if any(k in lower for k in FUNCTIONAL_VERBS):
        return "functional"
    return "functional"


# ─── NOTES / ADDITIONAL INFORMATION EXTRACTION ───────────────────────────────

_NOTES_PATTERN = re.compile(
    r'(?:notes?|note|justification|rationale|remark|see also|ref(?:erence)?)\s*[:\-]\s*(.+)',
    re.IGNORECASE
)

_SUB_REQ_PATTERN = re.compile(
    r'(?:sub[-\s]?requirement|sub[-\s]?req|derived\s+from|refers?\s+to|see)\s*[:\-]?\s*'
    r'([A-Za-z][A-Za-z0-9_\-\.]*\d[A-Za-z0-9_\-\.]*)',
    re.IGNORECASE
)


def extract_remarks_context(content: str, req_id: str) -> str:
    """
    Extracts Notes, Justification, sub-requirement references, and any
    additional explanatory text that appears between or after requirements.
    Returns a structured string for the Remarks/Additional Information field.
    Spec §3: Data between requirements (notes, justification, sub-requirements) must be captured.
    """
    remarks_parts = []

    # Extract explicit notes/justification lines
    for m in _NOTES_PATTERN.finditer(content):
        note_text = m.group(1).strip()
        if note_text and len(note_text) > 3:
            remarks_parts.append(f"Note: {note_text}")

    # Extract sub-requirement / cross-reference mentions
    for m in _SUB_REQ_PATTERN.finditer(content):
        ref = m.group(1).strip()
        remarks_parts.append(f"Sub-requirement/Reference: {ref}")

    # Extract enum definitions (e.g., "X is an enum with 2 values Active and Inactive")
    enum_matches = re.findall(
        r'(\w[\w\s]{1,40}?)\s+is\s+an\s+enum\s+with\s+\d+\s+values?\s+(\w+)\s+and\s+(\w+)',
        content, re.IGNORECASE
    )
    for signal_name, v1, v2 in enum_matches:
        remarks_parts.append(
            f"Enum definition: {signal_name.strip()} has values [{v1}, {v2}] — "
            f"test with both valid values and confirm invalid values are rejected."
        )

    # Basis of testing — requirement source
    if req_id:
        remarks_parts.append(
            f"Test basis: SRS requirement {req_id}. "
            f"Input values derived from SRS/ICD signal definitions."
        )

    return " | ".join(remarks_parts) if remarks_parts else ""


# ─── PRIMARY: LINE-BY-LINE REQUIREMENT PARSING ───────────────────────────────

def _clean_module_name(raw: str) -> Optional[str]:
    """
    Cleans a heading string into a usable module name.

    Rules (Req 7 + new module spec):
    - Strip leading section numbers  e.g. "1.1 ", "2.3.4 "
    - Strip trailing colons / punctuation
    - Strip [MODULE: ...] wrapper if present
    - Keep only alphabetical words and spaces (no digits, symbols)
    - Collapse whitespace; title-case result

    Examples:
      "1.1 Altitude Direction:"       -> "Altitude Direction"
      "1.2: Altitude Re-Direction:"   -> "Altitude Re Direction"
      "[MODULE: 2.1 Flight Control]"  -> "Flight Control"
      "3. Login Module"               -> "Login Module"
    """
    if not raw:
        return None

    # Unwrap [MODULE: ...] if present
    m = re.match(r'^\[MODULE:\s*(.+?)\]$', raw.strip(), re.IGNORECASE)
    if m:
        raw = m.group(1)

    raw = raw.strip()

    # Remove leading section numbers like "1.", "1.1 ", "2.3.4 ", "1.2:"
    raw = re.sub(r'^\d+(?:\.\d+)*[:\s]*', '', raw).strip()

    # Remove trailing colons/dots/spaces
    raw = raw.rstrip(':. ')

    # Keep only alphabetical characters and spaces
    raw = re.sub(r'[^A-Za-z\s\-]', ' ', raw)

    # Normalise hyphens/dashes to spaces
    raw = raw.replace('-', ' ')

    # Collapse whitespace and title-case
    cleaned = ' '.join(raw.split())
    if not cleaned:
        return None
    # Reject single-word non-descriptive headings that are not real module names
    _SKIP_WORDS = {
        'deleted', 'obsolete', 'reserved', 'tbd', 'tbc', 'na', 'none',
        'yes', 'no', 'general', 'other', 'misc', 'miscellaneous',
        'placeholder', 'empty', 'blank', 'unknown',
    }
    if cleaned.lower() in _SKIP_WORDS:
        return None  # caller will fall back to inherited or 'General'
    return cleaned


def parse_requirements_from_text(text: str) -> List[Dict]:
    """
    Reads document line by line.
    Tracks the active heading section ([MODULE:] markers injected by file_parser).

    Module assignment logic:
    - Each [MODULE:] marker sets the current_module for ALL subsequent requirements
      until the next [MODULE:] marker is seen.
    - When a requirement starts, the module is captured AT THAT MOMENT (not at flush),
      so each requirement correctly gets its own heading section.
    - If multiple requirements fall under the same heading, they all share that module.
    - If each requirement has its own heading, each gets its individual heading as module.

    This satisfies both cases described in the spec:
      Case 1: Multiple requirements under one heading → same module
      Case 2: Each requirement under its own heading → individual module

    Returns: list of { id, all_ids, content, module, notes_context }
    """
    lines           = text.splitlines()
    requirements    = []
    current_id      = None
    current_lines   = []
    current_all_ids = []
    current_module  = None      # module active when current requirement started
    pending_module  = None      # module heading seen but not yet assigned to a req
    between_notes   = []        # lines between reqs (accumulated as notes)

    def _flush():
        nonlocal current_id, current_lines, current_all_ids
        if current_id and current_lines:
            content = "\n".join(current_lines).strip()
            notes   = " ".join(between_notes).strip() if between_notes else ""
            requirements.append({
                "id":            current_id,
                "all_ids":       list(dict.fromkeys(current_all_ids)),
                "content":       content,
                "module":        current_module,   # module captured when this req started
                "notes_context": notes,
            })
        current_id      = None
        current_lines   = []
        current_all_ids = []

    for line in lines:
        raw = line.strip()
        if not raw:
            continue

        # Detect [MODULE: ...] markers (injected by file_parser for every bold heading)
        mod_raw = None
        m = _MODULE_MARKER.match(raw)
        if m:
            mod_raw = m.group(1).strip()

        if mod_raw is not None:
            # A new heading has been seen.
            # Store it as pending — it will be assigned to the NEXT requirement that starts.
            pending_module = _clean_module_name(mod_raw) or mod_raw
            continue

        # Skip ## heading lines (already handled via [MODULE:] on the next line)
        if raw.startswith('##'):
            continue

        start_ids = _ids_at_line_start(raw)

        if start_ids:
            # A new requirement starts here.
            # First flush the previous requirement (still using its own module).
            _flush()
            between_notes = []

            # Apply pending heading module to this new requirement.
            # If a new heading was seen since the last requirement, use it.
            # If no new heading since last requirement, inherit the same module
            # (multiple requirements under one heading).
            if pending_module is not None:
                current_module = pending_module
                pending_module = None          # consumed
            # else: current_module stays the same → grouped under same heading

            extra  = _all_ids_in_line(raw)
            merged = list(dict.fromkeys(start_ids + extra))
            current_id      = start_ids[0]
            current_all_ids = merged
            current_lines   = [raw]
        else:
            if current_id is not None:
                current_lines.append(raw)
                # Do NOT call _all_ids_in_line on continuation lines.
                # Body text regularly cross-references other requirement IDs
                # (e.g. "see also MRJ_MCU_SRS_005") — collecting those into
                # current_all_ids causes the chunk_data expander in main.py
                # to generate phantom requirement entries for them (18 vs 11 bug).
                # Only the IDs on the opening line are real IDs for this chunk.
            else:
                # Text before any requirement or between requirements
                between_notes.append(raw)

    _flush()
    return requirements


# ─── FALLBACK: SENTENCE-LEVEL CHUNKING ───────────────────────────────────────

def _has_decision_table(content: str) -> bool:
    sc_count = len(re.findall(r'\bSC[_\-]?\d+\b', content, re.IGNORECASE))
    has_in   = bool(re.search(r'\bInput[_\-]?\d+\b',  content, re.IGNORECASE))
    has_out  = bool(re.search(r'\bOutput[_\-]?\d+\b', content, re.IGNORECASE))
    return sc_count >= 2 and has_in and has_out


_FALLBACK_REQ_SIGNALS = re.compile(
    r'\b(shall|must|should|will|allow|enable|prevent|validate|calculate|'
    r'display|show|submit|process|create|update|delete|search|filter|'
    r'authenticate|authorize|authorise|notify|generate|export|import|'
    r'upload|download|verify|confirm|reject|approve|support|provide|'
    r'ensure|detect|monitor|store|retrieve|handle|manage|enforce|'
    r'require|permit|encrypt|trigger|send|receive|assign|track)\b',
    re.IGNORECASE
)

def _is_req_like(sentence: str) -> bool:
    s = sentence.strip()
    if len(s.split()) < 5:
        return False
    if s.endswith(':'):
        return False
    if re.match(r'^[\d\.\s]+$', s):
        return False
    return bool(_FALLBACK_REQ_SIGNALS.search(s))


def _split_sentences(text: str) -> List[str]:
    raw = re.split(r'(?<=[.!?])\s+', text)
    req = [s.strip() for s in raw if _is_req_like(s.strip())]
    if req:
        return req
    fallback = [s.strip() for s in raw if len(s.split()) >= 6]
    return fallback if fallback else [text]


# ─── PARENT-CHILD RELATIONSHIP DETECTION ────────────────────────────────────

def _detect_relationships(chunks: List[DocumentChunk]) -> List[DocumentChunk]:
    id_to_chunk: dict = {c.requirement_ids[0]: c for c in chunks if c.requirement_ids}

    for chunk in chunks:
        if not chunk.requirement_ids:
            continue
        req_id = chunk.requirement_ids[0]

        best_parent = None
        for candidate_id in id_to_chunk:
            if candidate_id == req_id:
                continue
            if not req_id.startswith(candidate_id):
                continue
            next_char = req_id[len(candidate_id):len(candidate_id)+1]
            if next_char not in ('.', '-', '_'):
                continue
            if best_parent is None or len(candidate_id) > len(best_parent):
                best_parent = candidate_id

        if best_parent:
            chunk.parent_id   = best_parent
            chunk.is_sub_req  = True
            parent_chunk = id_to_chunk[best_parent]
            parent_chunk.has_children = True
            if req_id not in parent_chunk.child_ids:
                parent_chunk.child_ids.append(req_id)

    for chunk in chunks:
        if chunk.is_sub_req and chunk.parent_id in id_to_chunk:
            parent_chunk  = id_to_chunk[chunk.parent_id]
            parent_text   = parent_chunk.content
            if not chunk.content.startswith("[Parent"):
                chunk.content = (
                    f"[Parent {chunk.parent_id}]: {parent_text} "
                    f"[Sub-Requirement {chunk.requirement_ids[0]}]: {chunk.content}"
                )

    return chunks


# ─── MAIN ENTRY POINT ─────────────────────────────────────────────────────────

def ingest_document(text: str, chunk_size_words: int = 1500) -> List[DocumentChunk]:
    """
    PRIMARY PATH — ID-based (document has requirement IDs):
      Line-by-line detection of ANY ID format.
      One DocumentChunk per requirement, exact ID from the document.
      Module is derived from document heading structure:
        - Each requirement captures the heading active when it starts.
        - If multiple requirements fall under the same heading, they share that module.
        - If each requirement has its own heading, each gets its own module.
      Module names are cleaned to alphabetical text only (Req 7).

    FALLBACK PATH — sentence-based (no IDs found):
      One DocumentChunk per sentence; keyword-based module detection.
    """
    if not text or not text.strip():
        return []

    parsed = parse_requirements_from_text(text)

    if parsed:
        chunks = []
        for i, req in enumerate(parsed):
            raw_content = req["content"]
            if not raw_content.strip():
                continue

            if _has_decision_table(raw_content):
                # Decision table — keep everything
                filtered_content = raw_content

            elif re.search(
                r'when\s+all\s+(?:the\s+)?following\s+(?:conditions\s+)?(?:are\s+)?(?:met|true|satisfied)',
                raw_content, re.IGNORECASE
            ) or re.search(
                r'when\s+(?:any\s+)?(?:one\s+)?(?:of\s+)?(?:the\s+)?following\s+(?:conditions\s+)?(?:are\s+)?(?:met|true|satisfied)',
                raw_content, re.IGNORECASE
            ):
                # Conditional requirement with bullet-point conditions.
                # Do NOT filter by _is_req_like — the condition bullets never
                # contain "shall/must" and would be silently dropped, leaving
                # _parse_conditional_requirement with incomplete input data.
                filtered_content = raw_content

            else:
                sentences     = re.split(r'(?<=[.!?])\s+', raw_content)
                req_sentences = [s.strip() for s in sentences if _is_req_like(s.strip())]
                filtered_content = " ".join(req_sentences) if req_sentences else raw_content

            primary_id = req["all_ids"][0] if req["all_ids"] else ""
            if primary_id and filtered_content.startswith(primary_id):
                filtered_content = filtered_content[len(primary_id):].lstrip(" :-.")

            # Module resolution (new spec):
            #   1. Use heading-derived module from parse_requirements_from_text
            #      (already cleaned by _clean_module_name, already handles individual
            #       and grouped requirements under same heading).
            #   2. If no heading was found, fall back to keyword detection.
            #   3. Always ensure the final module is alphabetical-only (Req 7).
            heading_module = req.get("module")
            if heading_module:
                doc_module = heading_module  # already cleaned by _clean_module_name
            else:
                # Keyword fallback — extract from content, then clean
                kw_module = detect_module(filtered_content)
                doc_module = _clean_module_name(kw_module) or kw_module

            # Final safety: strip any remaining non-alpha characters (Req 7)
            doc_module = re.sub(r'[^A-Za-z\s]', ' ', doc_module).strip()
            doc_module = re.sub(r'\s+', ' ', doc_module) or "General"

            # Gather notes context
            notes_context = req.get("notes_context", "")
            remarks_from_content = extract_remarks_context(raw_content, primary_id)
            full_notes = " | ".join(filter(None, [notes_context, remarks_from_content]))

            chunks.append(DocumentChunk(
                chunk_index      = i,
                module           = doc_module,
                requirement_type = classify_requirement(filtered_content),
                requirement_ids  = req["all_ids"],
                content          = filtered_content,
                notes_context    = full_notes,
            ))
        if chunks:
            return _detect_relationships(chunks)

    sentences = _split_sentences(text)
    result    = []
    for i, sentence in enumerate(sentences):
        s = sentence.strip()
        if not s:
            continue
        parts = s.split(None, 1)
        if len(parts) == 2:
            first = parts[0].strip('[]().,;:')
            m = re.match(r'^[A-Za-z][A-Za-z0-9_]{0,14}[-_.]?\d+(?:[-_.]\d+)*$', first)
            sm = re.match(r'^\d+(?:\.\d+)+$', first)
            if m or sm:
                s = parts[1].strip()
        # Clean keyword-detected module (Req 7)
        kw_mod = detect_module(s)
        clean_mod = re.sub(r'[^A-Za-z\s]', ' ', kw_mod).strip()
        clean_mod = re.sub(r'\s+', ' ', clean_mod) or "General"
        result.append(DocumentChunk(
            chunk_index      = i,
            module           = clean_mod,
            requirement_type = classify_requirement(s),
            requirement_ids  = [f"REQ-{i + 1:03d}"],
            content          = s,
            notes_context    = extract_remarks_context(s, f"REQ-{i + 1:03d}"),
        ))
    return result