# Codebase Merge — 2026-07-09

Merged `ai-testcase-tool-Merged.zip` (Hari's copy) with `ai-testcase-tool.zip`
(coworker's copy). These had diverged in **both directions** from a shared
ancestor — this was not a simple "apply my patch on top of theirs" merge.
Full rationale and file-by-file breakdown given in chat; summary:

- **Taken from coworker's copy as-is** (ahead of Hari's copy, no independent
  Hari changes to reconcile): `document_ingestion.py` (decision-table
  detection, remarks-context extraction, chunk-relationship detection),
  `file_parser.py` (hierarchical "H3 > H4" module naming), `models.py`
  (`selected_modules` field), `ScopeSelector.jsx` (multi-module checklist UI,
  duplicate-requirement-ID warnings).
- **Taken from Hari's copy as-is** (superset, coworker's copy had no
  independent changes to these): `constants.py`, `output_validator.py`,
  `mcp_server.py`, `output_generator.py`, `test_case_generator.py`,
  `ReviewPointsPanel.jsx` — i.e. all 5 files from the "Test Case Template
  Fixes" session below, plus the review-points refactor.
- **Hand-merged (both sides had independent, non-overlapping changes)**:
  - `main.py` — kept coworker's duplicate-ID detection, req-prefix filter,
    and multi-module scope filtering; layered in Hari's `_normalise_mcp_tc()`
    call-site fix (was defined but never called — silent data-shape bug) and
    Hari's rebuilt `/api/open-claude` endpoint (clipboard set via PowerShell
    `Set-Clipboard` from a prompt file, removing the race condition in the
    old browser-clipboard approach).
  - `App.jsx` — kept Hari's 6-step structured Claude Desktop prompt and the
    new POST-body clipboard flow; re-added `selected_modules` wiring in both
    `/api/generate` and `/api/generate/ai` request bodies so the multi-module
    selector keeps working end to end.
- **One unresolved judgment call, flagged for spot-check, not auto-decided**:
  `output_generator.py`'s `_remarks_bullets()` — Hari's copy removed the
  "Testing Type: X | Scenario Type: Y" bullet with a comment calling it
  redundant with dedicated template columns; coworker's copy still had the
  old bullet. Kept it removed (Hari's copy) since it came with an explicit
  rationale coworker's didn't contradict, but this wasn't in the dated
  changelog below, so it's worth Sandeep re-confirming it wasn't removed for
  an unrelated reason.

---

# Test Case Template Fixes — 2026-07-08

5 files changed: `output_generator.py`, `test_case_generator.py`, `mcp_server.py`,
`output_validator.py`, `constants.py`. Drop these into `backend/`, replacing the
existing copies. No dependency or schema changes — `models.py` is untouched.

All fixes were smoke-tested (unit-level + one full `generate_excel()` run) before
delivery; see the "How to verify" section at the bottom if you want to re-run them.

---

## 1. Test Details Description no longer repeats Design Methodology / Module

**Root cause:** `output_generator._col_e_test_details()` unconditionally appended
`"Design methodology: X."` and `"Module under test: Y."` to every description —
regardless of the fact that both already have dedicated columns.

**Fix:** Removed the append entirely. The description is now scenario- and
signal-specific text only.

## 2. State transitions now use arrow notation (`Invalid -> Valid`)

**Root cause:** Nothing was normalizing free-text input values, so prose like
"transition from Invalid to Valid" written by Claude passed straight through to
the Input Values column.

**Fix:** Added `_normalize_transition_value()` inside `output_generator._parse_signal_value()`
— the single choke point every input value passes through for both Excel and Word
export. It rewrites `"transition from X to Y"` / `"X to Y"` → `"X -> Y"`, but is
guarded against false positives:
- Numeric ranges are untouched (`"10 to 50"` stays as-is — both sides must start
  with a letter to match).
- Assignment phrasing is untouched (`"Set to True"` stays as-is — a stop-word list
  catches `set/reset/change/switch/move/assign`).

Also updated the MC/DC hint generator in `mcp_server.py` to hand Claude `->` instead
of the Unicode `→` arrow, so the guidance and the final output are consistent (and
`->` is safer across Excel/CSV/plain-text tooling than a Unicode arrow).

## 3. Test Details Description wording varies per test case

**Root cause:** `_col_e_test_details()` used one fixed string per scenario type
(`normal` / `boundary` / `edge` / `robustness` / `transition`) — identical wording
for every requirement.

**Fix:** Replaced the single template per scenario type with 3 phrasing variants
each, and the descriptions now interpolate the **real signal names** (from
`tc.inputs`) and **real output name** (parsed from `tc.expected_outcome`) instead of
generic language. Variant selection is deterministic (hashed on req ID + scenario
ID + scenario type) so the same test case always renders the same text on
regeneration, but different requirements land on different phrasing — no more
identical descriptions across the sheet.

## 4. Out-of-range Input Values are now concrete, not placeholder text

**Root cause:** `mcp_server._build_required_scenarios()`'s robustness hint literally
said `hint_inputs: ["Signal: <invalid/out-of-range value>"]` — a placeholder Claude
was supposed to replace, but sometimes didn't.

**Fix:** Added `_garbage_value_for()`, which resolves a real value per condition:
- Numeric signal with an ICD range declared → the actual computed out-of-range
  number (this was already being calculated elsewhere and just wasn't being used).
- Enum signal → `"INVALID_ENUM_CODE (not one of: Valid, Invalid, Not_Available)"`.
- Boolean signal → `"2 (undefined boolean state)"`.
- Unknown type → a named `CORRUPTED_<SIGNAL>_DATA` marker.

**Belt-and-suspenders:** also added a check in `output_validator.py` that flags (as
a warning, doesn't drop the TC) any saved input value that still looks like an
unfilled placeholder — `<...>`, bare `"out-of-range value"`, `"invalid value"`,
`"exact threshold"` — so if Claude ever writes the generic phrase anyway, it surfaces
in the validation report instead of silently reaching the RTM.

**Honesty note:** for enum/boolean signals I can't know your hardware's actual
"corrupted data" convention (e.g. an ARINC 429 NCD pattern), so those markers are
clearly-labelled placeholders you and Sandeep should sanity-check against the real
ICD — I didn't want to fabricate a domain-specific garbage code and present it as
fact.

## 5. Min/Max no longer suggested for Boolean/Enum outputs

**Root cause, two spots:**
- `test_case_generator.generate_remarks()` unconditionally added *"Note: No explicit
  boundary values in SRS — define min/max constraints before execution"* whenever a
  sentence lacked numeric-boundary keywords — which is most Boolean/Enum sentences.
- `output_generator._remarks_bullets()`'s boundary summary line always said
  *"minimum, maximum, min-1, max+1"* regardless of signal type.

**Fix:** Added `BOOL_ENUM_TRIGGERS` to `constants.py`. `generate_remarks()` now
checks whether the sentence/enum notes indicate a discrete signal and, if so, emits
*"Discrete-valued (Boolean/Enum) signal — verify every declared state is exercised;
numeric min/max does not apply"* instead. Added `_has_numeric_inputs()` to
`output_generator.py` so the boundary summary bullet only mentions min/max when at
least one input value is actually numeric.

## 6. All declared Enum values are now covered, with correct labels

**Root cause, two spots:**
- The MC/DC engine only ever generates 2 states per condition (`required_val` +
  `flip_val`) — correct for MC/DC itself, but it silently dropped any 3rd+ declared
  Enum value (e.g. `Not_Available`).
- The "signal unavailable" robustness hint hardcoded the word `"Unavailable"`
  instead of checking what the SRS actually declared (`Not_Available`).

**Fix:**
- Added a new scenario block (#12) in `mcp_server._build_required_scenarios()`: for
  any condition whose declared `enum_values` has more than 2 entries, it generates
  one additional `edge` scenario per value not already covered by the MC/DC pair —
  so `Valid` / `Invalid` / `Not_Available` all get exercised.
- Added `_unavailable_label()`, which searches the condition's declared enum values
  for a token meaning "unavailable/no data" (`Not_Available`, `NCD`, `No_Data`,
  etc.) and uses the **exact declared spelling** instead of a hardcoded guess.

---

## How to verify

```bash
cd backend
python3 -m py_compile output_generator.py test_case_generator.py mcp_server.py output_validator.py constants.py
```

Then regenerate a batch of test cases through the normal MCP flow and spot-check:
- Test Details Description column: no "Design methodology" / "Module under test" text,
  and two SC rows for the same requirement should read differently.
- Any transition-type input value: `X -> Y` format.
- Any robustness input value: a real value, not `<...>` or the phrase "out-of-range value".
- Remarks column for a Boolean/Enum-only requirement: no "define min/max constraints" line.
- A requirement with a 3+ value Enum: check the sheet for a scenario exercising the
  3rd value (it'll show up as an extra `edge`-type SC row) with the SRS-exact label.

## What I did *not* touch

Your `general-tc-skill` (used by Claude Desktop during generation) has a data-type
table that also frames Boolean/Enum "Boundary" testing as "(min, max)" — same root
issue as #5, just on the skill side rather than the code side. I didn't edit it since
it lives outside this repo and affects every project that uses that skill, not just
this one — let me know if you want that patched too and I'll do it as a separate,
explicit change.
