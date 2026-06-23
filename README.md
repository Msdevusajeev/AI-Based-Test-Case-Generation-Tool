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

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/upload` | Upload SRS file |
| POST | `/api/generate` | Generate test cases |
| GET | `/api/export/excel?session_id=` | Download `.xlsx` |
| GET | `/api/export/docx?session_id=` | Download `.docx` |
| GET | `/api/health` | Health check |

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
