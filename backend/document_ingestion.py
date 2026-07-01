import re
from typing import List, Dict, Optional
from models import DocumentChunk
from constants import MODULE_KEYWORDS, FUNCTIONAL_VERBS, NON_FUNCTIONAL_KEYWORDS


# ─────────────────────────────────────────────────────────────────────────────
#  FLEXIBLE REQUIREMENT ID DETECTION
#  Supports ANY format:
#
#  Standard   : FR-001, NFR-2.1, REQ_003, UC-01, BR-12, SR-001
#  Custom      : FUNC-001, PERF-01, SEC-003, SRS-001, SYS-01, INT-003
#  Short       : R001, F01, NF-01
#  Section Nos : 1.1, 2.3.1, 3.1.2.4
#  Bracketed   : [FR-001], (REQ-001)
#  Colon sep   : FR001:, REQ-001:
#  Dash sep    : PERF-01 - description
#  Underscore  : REQ_001, FUNC_003
# ─────────────────────────────────────────────────────────────────────────────

# Strips leading bullets / whitespace from line start
_BULLET_STRIP = re.compile(r'^[\s\-\*\•\►\▶\→\>\|#~=]+')

# Matches a FULL requirement ID token:
#   - 1 to 15 alphanumeric chars (must start with a letter)
#   - optional separator (- _ .)
#   - one or more digits
#   - optional repeated sub-numbers  (.1  -2  _3)
_FULL_ID = re.compile(
    r'^[\[\(]?'                          # optional opening bracket
    r'([A-Z][A-Z0-9_]{0,14}'            # prefix: starts with letter, up to 15 chars
    r'[-_.]?'                            # optional separator
    r'\d+'                               # required digits
    r'(?:[-_.]\d+)*)'                    # optional sub-numbers e.g. .1 .2
    r'[\]\)]?$',                         # optional closing bracket, end of token
    re.IGNORECASE,
)

# Matches a pure section number token: 1.1  2.3.1  3.1.2.4
_SECTION_ID = re.compile(r'^(\d+(?:\.\d+)+)$')

# Explicit label: "Requirement ID: FR-001"  or  "ID: REQ-001"
_EXPLICIT_LABEL = re.compile(
    r'(?:requirement\s+id|req\.?\s*id|id)\s*[:\-]\s*'
    r'([A-Z][A-Z0-9_\-\.]*\d)',
    re.IGNORECASE,
)


def _ids_at_line_start(line: str) -> List[str]:
    """
    Returns requirement IDs found AT THE START of a line.
    This is the signal that a line begins a new requirement block.

    Algorithm:
    1. Strip leading bullets / whitespace
    2. Extract the first token (split on SPACE only — NOT on dash/underscore
       so that FR-001 stays as one token, not split into FR and 001)
    3. Clean brackets/punctuation from the token
    4. Match against the full ID pattern and section-number pattern
    """
    # Check for explicit label anywhere in line first
    m = _EXPLICIT_LABEL.search(line)
    if m:
        return [m.group(1).upper()]

    # Strip leading noise characters
    stripped = _BULLET_STRIP.sub('', line).strip()
    if not stripped:
        return []

    # Extract first token — split only on SPACES (dash is part of the ID)
    parts      = stripped.split()
    first_tok  = parts[0].strip('[]().,;:') if parts else ''
    if not first_tok:
        return []

    # Try full ID pattern
    m = _FULL_ID.match(first_tok)
    if m:
        candidate = m.group(1).upper()
        # Reject pure numbers (list items like "1." become "1" after strip)
        if not candidate.isdigit():
            return [candidate]

    # Try section number (e.g. 1.1, 2.3.1)
    m = _SECTION_ID.match(first_tok)
    if m:
        return [m.group(1)]

    # Last resort: check first two tokens joined (handles "FR - 001")
    if len(parts) >= 2:
        combined = ''.join(parts[:3]).strip('[]().,;:')
        m = _FULL_ID.match(combined)
        if m:
            candidate = m.group(1).upper()
            if not candidate.isdigit():
                return [candidate]

    return []


def _all_ids_in_line(line: str) -> List[str]:
    """
    Finds ALL IDs referenced anywhere in a line.
    Used to build the complete all_ids list (including cross-references).
    """
    found = []

    # Explicit labels
    for m in _EXPLICIT_LABEL.finditer(line):
        found.append(m.group(1).upper())

    # All ID-like tokens anywhere in the line
    for token in re.split(r'[\s,;]+', line):
        clean = token.strip('[]().,;:')
        if not clean:
            continue
        m = _FULL_ID.match(clean + ' ')  # add space so end-anchor works
        # Re-try without end anchor for mid-sentence references
        m2 = re.match(
            r'^[\[\(]?([A-Z][A-Z0-9_]{0,14}[-_.]?\d+(?:[-_.]\d+)*)[\]\)]?$',
            clean, re.IGNORECASE
        )
        if m2:
            candidate = m2.group(1).upper()
            if not candidate.isdigit() and len(candidate) >= 2:
                found.append(candidate)
        else:
            sm = _SECTION_ID.match(clean)
            if sm:
                found.append(sm.group(1))

    # Deduplicate preserving order
    seen, unique = set(), []
    for x in found:
        if x not in seen:
            seen.add(x)
            unique.append(x)
    return unique


# ─── MODULE DETECTION ─────────────────────────────────────────────────────────

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


# ─── CORE: LINE-BY-LINE REQUIREMENT PARSING ──────────────────────────────────

def parse_requirements_from_text(text: str) -> List[Dict]:
    """
    Reads the document line by line.
    When a line STARTS WITH a requirement ID → close the previous block,
    open a new one.
    Lines with no ID at the start → appended to the current block.
    Returns: list of { id, all_ids, content }
    """
    lines         = text.splitlines()
    requirements  = []
    current_id    = None
    current_lines = []
    current_all_ids = []

    for line in lines:
        raw = line.strip()
        if not raw:
            continue

        start_ids = _ids_at_line_start(raw)

        if start_ids:
            # Save previous block
            if current_id and current_lines:
                requirements.append({
                    "id":      current_id,
                    "all_ids": list(dict.fromkeys(current_all_ids)),
                    "content": " ".join(current_lines).strip(),
                })
            # Start new block
            extra = _all_ids_in_line(raw)
            merged = list(dict.fromkeys(start_ids + extra))

            current_id      = start_ids[0]
            current_all_ids = merged
            current_lines   = [raw]
        else:
            if current_id is not None:
                current_lines.append(raw)
                # Collect cross-reference IDs from continuation lines
                for ref in _all_ids_in_line(raw):
                    if ref not in current_all_ids:
                        current_all_ids.append(ref)

    # Flush last block
    if current_id and current_lines:
        requirements.append({
            "id":      current_id,
            "all_ids": list(dict.fromkeys(current_all_ids)),
            "content": " ".join(current_lines).strip(),
        })

    return requirements


# ─── FALLBACK: SENTENCE-BASED CHUNKING ───────────────────────────────────────

def _split_sentences(text: str) -> List[str]:
    sentences = re.split(r'(?<=[.!?])\s+(?=[A-Z])', text)
    return [s.strip() for s in sentences if s.strip() and len(s.split()) >= 5]


def _chunk_text(text: str, max_words: int = 1500) -> List[str]:
    sentences      = _split_sentences(text)
    chunks, cur, w = [], [], 0
    for sent in sentences:
        sw = len(sent.split())
        if w + sw > max_words and cur:
            chunks.append(" ".join(cur))
            cur, w = [sent], sw
        else:
            cur.append(sent)
            w += sw
    if cur:
        chunks.append(" ".join(cur))
    return chunks if chunks else [text]


# ─── MAIN ENTRY POINT ─────────────────────────────────────────────────────────

def ingest_document(text: str, chunk_size_words: int = 1500) -> List[DocumentChunk]:
    """
    PRIMARY PATH  — ID-based:
      Detects requirement IDs in ANY format at line starts.
      Creates one DocumentChunk per requirement with exact IDs from the document.

    FALLBACK PATH — no IDs found:
      Sentence-based chunking with auto-assigned REQ-001, REQ-002 ...
    """
    if not text or not text.strip():
        return []

    # ── Primary ───────────────────────────────────────────────────────────────
    parsed = parse_requirements_from_text(text)
    if parsed:
        chunks = []
        for i, req in enumerate(parsed):
            content = req["content"]
            if not content.strip():
                continue
            chunks.append(DocumentChunk(
                chunk_index      = i,
                module           = detect_module(content),
                requirement_type = classify_requirement(content),
                requirement_ids  = req["all_ids"],
                content          = content,
            ))
        if chunks:
            return chunks

    # ── Fallback ──────────────────────────────────────────────────────────────
    raw_chunks = _chunk_text(text, chunk_size_words)
    result = []
    for i, chunk in enumerate(raw_chunks):
        if not chunk.strip():
            continue
        result.append(DocumentChunk(
            chunk_index      = i,
            module           = detect_module(chunk),
            requirement_type = classify_requirement(chunk),
            requirement_ids  = [f"REQ-{i + 1:03d}"],
            content          = chunk,
        ))
    return result
