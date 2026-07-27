# Rule-Based Test Case Generator

**No API key. No LLM. No Ollama. Fully offline.**

Generates comprehensive test cases from SRS documents (PDF, DOCX, XLSX) using a
deterministic rule-based NLP engine built with spaCy, keyword pattern matching,
and template expansion.

---

## Features

- Accepts PDF, Word (.docx), and Excel (.xlsx) SRS documents
- Generates 4 scenario types per requirement: Normal · Boundary · Edge · Robustness
- Auto-assigns Priority (P1/P2/P3), Design Methodology, Testing Type, and Remarks by rule
- Exports to Excel (`test_cases.xlsx`, sheet: `test_cases`) and Word (`.docx`)
- Deduplication via `difflib.SequenceMatcher` (threshold: 0.85)
- 17-column output schema with full traceability
- React frontend with filters, search, and paginated table

---

## Output Columns

| Column | Description |
|--------|-------------|
| Traceability Req-ID | Source requirement ID |
| Test Case ID | TC_VD_001 / TC_IT_001 / TC_UT_001 |
| Scenario ID | SC-001, SC-002 … |
| Priority | P1 / P2 / P3 |
| Test Case Objective | Verify that [subject] [action] under [scenario] conditions |
| Test Precondition | Pre-execution conditions |
| Test Steps | Numbered execution steps |
| Test Inputs (Conditions/Values) | Exact input values |
| Test Case Design Methodology | Black Box / BVA / EP / Error Guessing |
| Dependent Test Cases | IDs of prerequisites |
| Expected Outcome | Precise expected result |
| Test Environment | Dev / QA / UAT / Prod |
| Remarks / Additional Info | Auto-detected risks and compliance notes |
| Module | Detected module (Login, Payment, API…) |
| Requirement Type | functional / non-functional |
| Scenario Type | normal / boundary / edge / robustness |
| Testing Type | verification / validation / integration |

---

## Setup

### Prerequisites
- Python 3.11+
- Node.js 18+
- No API key. No internet dependency for generation.

### 1 — Backend

```bash
cd backend
pip install -r requirements.txt

# Optional: improves sentence detection (tool works without it)
python -m spacy download en_core_web_sm

# Copy and edit config if needed
cp ../.env.example .env

# Start backend
uvicorn main:app --reload --port 8000
```

### 2 — Frontend

```bash
cd frontend
npm install
npm run dev
```

### 3 — Open browser

```
http://localhost:8000
```

---

## Docker (backend only)

```bash
docker build -t testcase-generator .
docker run -p 8000:8000 testcase-generator
```

Then run the frontend separately with `npm run dev`.

---

## How Test Cases Are Generated (No LLM)

1. **Document parsing** — PyMuPDF / python-docx / openpyxl extract clean text
2. **Ingestion** — spaCy segments sentences; keyword dicts detect module and req type; regex extracts requirement IDs
3. **Generation** — For each requirement sentence, 4 test cases are built via template expansion:
   - `normal` → Black Box Testing
   - `boundary` → Boundary Value Analysis
   - `edge` → Equivalence Partitioning
   - `robustness` → Error Guessing
4. **Enrichment** — Priority, methodology, environment, and remarks assigned by deterministic rules
5. **Deduplication** — `difflib.SequenceMatcher` removes objectives with similarity > 0.85

---

## Document/Chunk Caching (content-hash based)

To avoid re-parsing and re-ingesting a document you've already processed —
including across app restarts — the backend keeps a persistent, content-hash
cache in `backend/.cache/`:

| Cache | Keyed by | Skips |
|-------|----------|-------|
| `backend/.cache/text/*.json` | SHA-256 of the raw uploaded file bytes | `parse_file()` — PDF/DOCX/XLSX text extraction |
| `backend/.cache/chunks/*.json` | SHA-256 of parsed text + chunk size + `CACHE_FORMAT_VERSION` | `ingest_document()` — sentence/requirement chunking |

Both `/api/generate` (rule-based) and `/api/generate/ai` (Claude AI / MCP)
route through a shared `_ingest_with_cache()` helper in `main.py`, so a cache
hit benefits either path.

**Multi-document batching:** `/api/generate/ai` accepts either
`{"session_id": "..."}` (single document, original behavior) or
`{"session_ids": ["...", "...", "..."]}` — the latter merges requirement
chunks from every listed upload session into one combined queue before Claude
AI batches through it via `get_generated_test_cases`. Each queued entry is
tagged with `source_session_id` / `source_filename` for traceability.

**Cache lifetime & invalidation:**
- Survives process restarts and EXE rebuilds (`refresh.bat`, `build_exe.bat`,
  including "Full clean rebuild") — the cache lives under `backend/.cache/`,
  which none of those touch.
- Does **not** survive deleting/reinstalling the whole app folder, since
  `.cache/` is nested inside it. Point `_CACHE_DIR` in `doc_cache.py` at a
  location outside the app folder if you need it to survive a full reinstall.
- If you change `document_ingestion.py`'s logic (new regex, new module
  rules, etc.) or `CHUNK_SIZE_WORDS`, bump `CACHE_FORMAT_VERSION` in
  `doc_cache.py` (or call `POST /api/debug/cache/clear`) so stale cached
  chunks aren't served under the old logic.
- What does **not** persist across a restart regardless of caching: the
  in-memory `sessions` / `generation_queue` dicts (your upload → session_id
  mapping). Re-upload the same file through the GUI after a restart — the
  parse/ingest work itself will be skipped via the cache, but you'll get a
  fresh `session_id`.

---

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/upload` | Upload SRS file (content-hash cached — see above) |
| POST | `/api/generate` | Generate test cases (rule-based, uses cached ingestion) |
| POST | `/api/generate/ai` | Queue requirements for Claude AI/MCP — accepts `session_id` or `session_ids: [...]` for multi-document batching |
| GET | `/api/export/excel?session_id=` | Download `.xlsx` |
| GET | `/api/export/docx?session_id=` | Download `.docx` |
| GET | `/api/health` | Health check |
| GET | `/api/debug/cache` | Show count of cached documents/chunk-sets |
| POST | `/api/debug/cache/clear` | Wipe the on-disk text/chunk cache |

---

## Project Structure

```
ai-testcase-tool/
├── backend/
│   ├── main.py               # FastAPI app + endpoints
│   ├── models.py             # Pydantic schemas
│   ├── constants.py          # Keyword dicts + templates
│   ├── config.py             # Config (no API key)
│   ├── file_parser.py        # PDF / DOCX / XLSX parsing
│   ├── document_ingestion.py # Chunking + classification
│   ├── doc_cache.py          # Content-hash cache for parsed text + chunks
│   ├── test_case_generator.py# Rule-based NLP engine
│   ├── output_generator.py   # Excel + Word export
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── App.jsx
│   │   ├── index.css
│   │   └── components/
│   │       ├── UploadPanel.jsx
│   │       ├── ReviewPointsPanel.jsx
│   │       ├── SummaryBar.jsx
│   │       └── ResultsTable.jsx
│   ├── index.html
│   ├── package.json
│   ├── vite.config.js
│   └── tailwind.config.js
├── .env.example
├── Dockerfile
└── README.md
```