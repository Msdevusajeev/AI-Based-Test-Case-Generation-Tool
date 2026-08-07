# ICD/SRS Cross-Reference — Session Changes

## Bugs found (confirmed by reading, then by execution)

1. **`main.py` `/api/generate`**: fetched `icd_text`/`supporting_text`, built a
   `combined_text` variable, and never used it. ICD upload had zero effect on
   the rule-based generator.
2. **`main.py` `/api/generate/ai`**: ICD text was logged as "informational
   only, not yet merged into ingestion" — same gap, self-documented in the
   original code.
3. **`test_case_generator.py`**: `_detect_threshold_condition` /
   `_get_flip_value` already had regex expecting `"Name | Type | Lo to Hi"`
   in `chunk.content` — but `document_ingestion.ingest_document()` ingests
   SRS text only, so that regex could never see real ICD data. It only ever
   fired if the SRS text happened to contain a literal pipe-table row.
4. **Deeper gap**: even when a threshold *is* stated inline, BVA/ECP scenarios
   only fired when the SRS sentence contained an explicit numeric comparison
   (`<= 124`, etc.). A requirement that just names an ICD-defined signal with
   no inline comparison got zero boundary coverage.
5. **Caught during testing, not code review**: the first working version of
   the new per-parameter boundary sweep had `deduplicate()` silently drop
   9 of 14 generated test cases, because its fuzzy-match dedup buckets by
   `(req_id, scenario_type)` and several genuinely-distinct ICD boundary
   cases share almost all wording. Fixed by adding a protected methodology
   name, same mechanism already used for MC/DC and decision-table cases.

## New/changed files

- **`backend/icd_parser.py`** (new) — parses ICD/supporting-doc text into
  signal specs (name, type, range, unit, enum values). Handles three real
  table shapes produced by `file_parser.py`: docx pipe-rows, xlsx
  "Header: Value" line groups, and PDF's tendency to collapse tight-column
  tables into concatenated text with no whitespace.
- **`backend/models.py`** — `DocumentChunk` gained `icd_context` (text) and
  `icd_signals` (structured dict) fields. `TestCase.scenario_type` gained
  `"invalid_input"`.
- **`backend/document_ingestion.py`** — new `attach_icd_context()`:
  cross-references SRS chunks against parsed ICD signals.
- **`backend/main.py`** — both generate endpoints now actually call
  `attach_icd_context()` per session/document instead of discarding the ICD
  text; AI-endpoint's chunk content sent to Claude also includes the
  resolved ICD context.
- **`backend/test_case_generator.py`** — `raw_content` now includes ICD
  context so existing threshold/MC-DC regex sees real ICD ranges; new
  `_icd_full_range_scenarios()` + generation block produces the full
  Min / Min+1 / Nominal / Max-1 / Max / Below-Min(invalid) / Above-Max(invalid)
  sweep per ICD-referenced parameter, independent of whether the SRS states
  an explicit comparison. Tagged with a dedup-protected methodology name.
- **`backend/output_validator.py`**, **`output_generator.py`**,
  **`frontend/src/*`** — `invalid_input` scenario type registered
  consistently (validator normalization, Excel remarks text, React badge
  colors/filters, Verification Depth panel).

## Verified by direct execution (not just read-through)

- Docx-style, xlsx-style, and PDF-concatenated ICD table formats all parse
  correctly — checked against the exact "Engine Speed / Time" example.
- `ingest_document()` → `attach_icd_context()` → `generate_all()` full chain
  run against synthetic SRS+ICD text: produces 7 scenarios per numeric
  signal and a valid/invalid set per enum signal, all surviving dedup.
- `compute_gui_display_fields()` runs clean on the resulting test cases
  (Excel/Word export path).

## Not yet done

- Not tested against a real production SRS/ICD file (none was in the
  uploaded zip — only source code). Recommend running one live MRJ-style
  SRS/ICD pair through `/api/generate` before trusting this for a real
  RTM/Sandeep review pass.
- MCP path (`mcp_server.py`, used for the typed-into-chat workflow) does not
  ingest uploaded ICD files at all — this fix only applies to the FastAPI
  upload+generate REST path. If ICD cross-referencing is needed in the MCP
  session workflow too, that's separate work.
