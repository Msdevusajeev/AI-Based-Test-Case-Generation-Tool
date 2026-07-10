# backend/mcp_server.py
# Claude Desktop MCP Server — AI-First Test Case Generation
#
# Generation strategy:
#   1. NLP engine extracts structured context from each requirement:
#        - Filtered requirement sentences
#        - Subject + action phrases
#        - Inferred module, requirement type, testing type, priority, methodology
#        - Notes context (enums, cross-references, sub-requirement links)
#   2. The structured NLP context is sent to Claude AI as INPUT
#   3. Claude AI generates all test case fields from scratch using that context
#   4. save_enhanced_test_cases persists the AI-generated results to the React UI
#
# NLP module role: extraction & classification only (no test case objects created)
# Claude AI role:  test case generation (objective, steps, preconditions, outcome, remarks)
#
# No API key. No Ollama. No LLM models.
# Claude Desktop is the AI layer via MCP.

import json
import sys
import os
import io
import asyncio

if sys.platform == 'win32' and not hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(
        io.BufferedWriter(io.FileIO(1, mode='wb', closefd=False)),
        encoding='utf-8', errors='replace',
        line_buffering=False, write_through=True,
    )

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

server      = Server("tc-tool")
BACKEND_URL = "http://localhost:8000"


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [

        types.Tool(
            name="get_tool_status",
            description="Returns TC Tool status. Call to verify connection.",
            inputSchema={"type": "object", "properties": {}}
        ),

        types.Tool(
            name="get_generated_test_cases",
            description=(
                "Extracts NLP context from queued SRS requirements. "
                "For large documents use batch_index+batch_size to avoid the 1MB MCP limit. "
                "Call repeatedly with batch_index=0,1,2,... until is_last_batch=true. "
                "After ALL batches done call save_enhanced_test_cases ONCE with all test cases."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "batch_index": {
                        "type": "integer",
                        "description": "Zero-based batch number. Start at 0, increment by 1 each call. Default: 0",
                        "default": 0
                    },
                    "batch_size": {
                        "type": "integer",
                        "description": "Requirements per batch. Default 15. Use 10 for complex SRS with long requirements.",
                        "default": 15
                    }
                }
            }
        ),

        types.Tool(
            name="save_enhanced_test_cases",
            description=(
                "Saves the AI-generated test cases to the React UI. "
                "Call this after generating test cases from the NLP context provided by "
                "get_generated_test_cases. Pass the complete list of test cases with ALL fields."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "test_cases": {
                        "type": "array",
                        "description": "The AI-generated test cases with all required fields populated",
                        "items": {"type": "object"}
                    }
                },
                "required": ["test_cases"]
            }
        ),

        types.Tool(
            name="generate_for_requirement",
            description=(
                "Extracts NLP context from a single requirement typed directly in chat "
                "and returns it for Claude AI to generate test cases. "
                "Results are automatically saved to the React UI."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "requirement_text": {"type": "string", "description": "Full requirement text"},
                    "requirement_id":   {"type": "string", "description": "e.g. FR-001", "default": "REQ-001"},
                    "module":           {"type": "string", "description": "e.g. Navigation", "default": "General"}
                },
                "required": ["requirement_text"]
            }
        ),

    ]


@server.call_tool()
async def call_tool(
    name: str,
    arguments: dict,
) -> list[types.TextContent]:

    if name == "get_tool_status":
        result = json.dumps({
            "status":   "running",
            "engine":   "NLP extraction + Claude AI generation",
            "version":  "2.0.0",
            "mode":     "Claude Desktop MCP",
            "strategy": (
                "NLP module extracts requirement sentences, subjects, actions, "
                "and classification metadata. Claude AI generates all test case "
                "fields from scratch using that structured context."
            ),
            "tools": [
                "get_generated_test_cases — extract NLP context for Claude AI to generate test cases",
                "save_enhanced_test_cases — save AI-generated results to React UI",
                "generate_for_requirement — extract NLP context for a single requirement in chat",
            ]
        }, indent=2)

    elif name == "get_generated_test_cases":
        _bi = int(arguments.get("batch_index", 0))
        _bs = int(arguments.get("batch_size",  15))
        loop   = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: _extract_nlp_context_for_queue(batch_index=_bi, batch_size=_bs)
        )

    elif name == "save_enhanced_test_cases":
        test_cases = arguments.get("test_cases", [])
        is_partial = bool(arguments.get("is_partial", False))
        loop       = asyncio.get_event_loop()
        result     = await loop.run_in_executor(
            None, lambda: _save_enhanced_cases(test_cases, is_partial=is_partial)
        )

    elif name == "generate_for_requirement":
        req_text = arguments.get("requirement_text", "")
        req_id   = arguments.get("requirement_id", "REQ-001")
        module   = arguments.get("module", "General")
        loop     = asyncio.get_event_loop()
        result   = await loop.run_in_executor(
            None, _extract_and_generate_single, req_text, req_id, module
        )

    else:
        result = json.dumps({"error": f"Unknown tool: {name}"})

    return [types.TextContent(type="text", text=result)]


# ─── TOOL IMPLEMENTATIONS ─────────────────────────────────────────────────────


def _extract_req_content(req_id: str, full_content: str) -> str:
    """
    Extract the text block belonging to req_id from full_content.
    If full_content has multiple requirements, returns only the section
    from req_id's line to the next requirement ID (or end of text).
    Falls back to full_content if req_id not found.
    """
    import re

    # Find where this req_id appears in the content
    # Match patterns like "REQ_001:", "REQ_001 ", "REQ-001:", etc.
    escaped = re.escape(req_id)
    start_m = re.search(rf'(?:^|\n)\s*{escaped}\b', full_content, re.IGNORECASE)
    if not start_m:
        return full_content   # req_id not found, use full content

    start = start_m.start()

    # Find the next requirement ID after this one
    # Look for patterns like REQ_XXX, MRJ_XXX, SRS_XXX etc. on a new line
    next_req = re.search(
        r'\n\s*(?:[A-Z][A-Z0-9]*[_-][A-Z0-9][A-Z0-9_-]{1,40})(?:\s*:|\s+[Tt]he|\s+shall)',
        full_content[start + len(req_id):],
        re.IGNORECASE
    )
    if next_req:
        end = start + len(req_id) + next_req.start()
        return full_content[start:end].strip()

    return full_content[start:].strip()

def _build_required_scenarios(req_id: str, content: str,
                               sentence_contexts: list) -> list:
    """
    Pre-calculate every scenario that MUST be generated for this requirement.
    Returns a list of scenario stubs with scenario_type, scenario_id, and
    a hint for the input values — Claude fills in all remaining fields.
    """
    import re

    try:
        from test_case_generator import _parse_conditional_requirement
        parsed = _parse_conditional_requirement(content)
        conditions   = parsed.get("conditions", [])
        output_name  = parsed.get("output_name", "Output")
        output_true  = parsed.get("output_true_val",  "True")
        output_false = parsed.get("output_false_val", "False")
        logic        = parsed.get("logic_type", "AND")
    except Exception:
        conditions, output_name = [], "Output"
        output_true, output_false, logic = "True", "False", "AND"

    scenarios = []
    sc = 1

    def sid():
        nonlocal sc
        s = f"SC_{sc:03d}"; sc += 1; return s

    def _garbage_value_for(cond: dict) -> str:
        """
        Req 4: never hand Claude the literal placeholder '<invalid/
        out-of-range value>' — resolve a concrete invalid/garbage value for
        this specific condition instead.
          - Numeric condition with an ICD range: flip_val IS already a real
            number just outside the valid range — use it directly.
          - Enum condition: a token that is provably outside the declared
            valid set.
          - Boolean condition: a value outside {True, False}.
          - Otherwise: a clearly-labelled malformed-data marker naming the
            signal, so the reviewer knows exactly what garbage to inject.
        """
        flip = str(cond.get("flip_val", "")).strip()
        try:
            float(flip)
            return flip  # genuine ICD-derived out-of-range number
        except (TypeError, ValueError):
            pass
        enum_vals = cond.get("enum_values") or []
        if enum_vals:
            return f"INVALID_ENUM_CODE (not one of: {', '.join(enum_vals)})"
        if str(cond.get("required_val", "")).strip().lower() in (
            "true", "false", "1", "0", "yes", "no", "enabled", "disabled"
        ):
            return "2 (undefined boolean state)"
        return f"CORRUPTED_{cond['name'].upper().replace(' ', '_')}_DATA"

    def _unavailable_label(cond: dict) -> str:
        """
        Req 6: use the SRS-declared enum token for the 'unavailable' /
        'no data' state (e.g. 'Not_Available') instead of hardcoding the
        generic word 'Unavailable', which may not match what's actually
        declared in the requirement's Notes.
        """
        for v in cond.get("enum_values", []) or []:
            if re.sub(r"[\s_-]", "", v).lower() in (
                "notavailable", "unavailable", "nodata", "nocompute", "ncd", "invaliddata"
            ):
                return v
        return "Unavailable"

    # ── 1. NORMAL — all conditions at required value ──────────────────────────
    normal_inputs = [f"{c['name']}: {c['required_val']}" for c in conditions]
    scenarios.append({
        "scenario_id":   sid(),
        "scenario_type": "normal",
        "hint_inputs":   normal_inputs or ["All inputs at nominal/active values"],
        "hint_outcome":  f"{output_name} = {output_true}",
        "hint_objective": f"Verify {output_name} is {output_true} when all conditions are simultaneously met",
    })

    # ── 2. BOUNDARY — flip one condition at a time (MC/DC) ───────────────────
    for cond in conditions:
        flip_inputs = []
        for c in conditions:
            val = c["flip_val"] if c["name"] == cond["name"] else c["required_val"]
            flip_inputs.append(f"{c['name']}: {val}")
        expected = output_false if logic == "AND" else (
            output_true if any(
                c["required_val"] != c["flip_val"] and c["name"] != cond["name"]
                for c in conditions
            ) else output_false
        )
        scenarios.append({
            "scenario_id":   sid(),
            "scenario_type": "boundary",
            "hint_inputs":   flip_inputs,
            "hint_outcome":  f"{output_name} = {expected}",
            "hint_objective": f"Verify {output_name} changes to {expected} when {cond['name']} transitions to {cond['flip_val']} (MC/DC independence)",
        })

    # ── 3. BOUNDARY — exact threshold / min and max ───────────────────────────
    scenarios.append({
        "scenario_id":   sid(),
        "scenario_type": "boundary",
        "hint_inputs":   [f"{c['name']}: <exact threshold value>" for c in conditions[:2]] or ["Input at exact activation threshold"],
        "hint_outcome":  f"{output_name} = {output_true} (exactly at threshold)",
        "hint_objective": f"Verify {output_name} at exact boundary/threshold value of each numeric input",
    })

    # ── 4. EDGE — all conditions at flip/inactive value ──────────────────────
    all_flip = [f"{c['name']}: {c['flip_val']}" for c in conditions]
    scenarios.append({
        "scenario_id":   sid(),
        "scenario_type": "edge",
        "hint_inputs":   all_flip or ["All inputs at inactive/false/zero values"],
        "hint_outcome":  f"{output_name} = {output_false}",
        "hint_objective": f"Verify {output_name} is {output_false} when ALL conditions are simultaneously inactive",
    })

    # ── 5. EDGE — conflicting / only one condition active ────────────────────
    if conditions:
        one_active = [
            f"{c['name']}: {c['required_val'] if i == 0 else c['flip_val']}"
            for i, c in enumerate(conditions)
        ]
        scenarios.append({
            "scenario_id":   sid(),
            "scenario_type": "edge",
            "hint_inputs":   one_active,
            "hint_outcome":  f"{output_name} = {output_false if logic == 'AND' else output_true}",
            "hint_objective": f"Verify system handles partially satisfied conditions correctly",
        })

    # ── 6. ROBUSTNESS — invalid / out-of-range input ─────────────────────────
    scenarios.append({
        "scenario_id":   sid(),
        "scenario_type": "robustness",
        "hint_inputs":   [f"{conditions[0]['name']}: {_garbage_value_for(conditions[0])}"] if conditions else ["Input: 0xFFFF (undefined/corrupted value)"],
        "hint_outcome":  f"{output_name} = {output_false} (system handles invalid input gracefully)",
        "hint_objective": "Verify system remains stable and output is safe when an input receives an invalid/out-of-range value",
    })

    # ── 7. ROBUSTNESS — signal unavailable / communication loss ──────────────
    scenarios.append({
        "scenario_id":   sid(),
        "scenario_type": "robustness",
        "hint_inputs":   [f"{c['name']}: {_unavailable_label(c)}" for c in (conditions[:2] if conditions else [{"name": "Input signal", "enum_values": []}])],
        "hint_outcome":  f"{output_name} = {output_false} (safe state on signal loss)",
        "hint_objective": "Verify system enters safe state when input signals become unavailable or communication is lost",
    })

    # ── 8. ROBUSTNESS — recovery after fault ─────────────────────────────────
    scenarios.append({
        "scenario_id":   sid(),
        "scenario_type": "robustness",
        "hint_inputs":   normal_inputs or ["Inputs restored to valid nominal values"],
        "hint_outcome":  f"{output_name} = {output_true} (system recovers correctly)",
        "hint_objective": f"Verify {output_name} recovers to {output_true} after invalid inputs return to valid range",
    })

    # ── 9. TRANSITION — inactive -> active ────────────────────────────────────
    scenarios.append({
        "scenario_id":   sid(),
        "scenario_type": "transition",
        "hint_inputs":   (
            [f"{conditions[0]['name']}: {conditions[0]['flip_val']} -> {conditions[0]['required_val']}"]
            + [f"{c['name']}: {c['required_val']}" for c in conditions[1:]]
        ) if conditions else ["State: Inactive -> Active"],
        "hint_outcome":  f"{output_name} transitions from {output_false} to {output_true}",
        "hint_objective": f"Verify {output_name} activates correctly as conditions transition from inactive to active state",
    })

    # ── 10. TRANSITION — active -> inactive ───────────────────────────────────
    scenarios.append({
        "scenario_id":   sid(),
        "scenario_type": "transition",
        "hint_inputs":   (
            [f"{conditions[0]['name']}: {conditions[0]['required_val']} -> {conditions[0]['flip_val']}"]
            + [f"{c['name']}: {c['required_val']}" for c in conditions[1:]]
        ) if conditions else ["State: Active -> Inactive"],
        "hint_outcome":  f"{output_name} transitions from {output_true} to {output_false}",
        "hint_objective": f"Verify {output_name} deactivates correctly when a condition transitions from active to inactive",
    })

    # ── 11. TRANSITION — partial activation (if multi-condition AND) ─────────
    if len(conditions) >= 2 and logic == "AND":
        partial = [
            f"{c['name']}: {c['required_val'] if i == 0 else c['flip_val']}"
            for i, c in enumerate(conditions)
        ]
        scenarios.append({
            "scenario_id":   sid(),
            "scenario_type": "transition",
            "hint_inputs":   partial,
            "hint_outcome":  f"{output_name} = {output_false} (partial activation not sufficient)",
            "hint_objective": "Verify output remains inactive when only a subset of AND conditions are met during activation sequence",
        })

    # ── 12. EDGE — full enumeration coverage for 3+ value Enum conditions ────
    # Req 6: MC/DC only needs required_val + flip_val (2 states). If the SRS
    # declares a 3rd (or more) valid Enum value — e.g. Valid / Invalid /
    # Not_Available — it's covered here so no declared state is ever skipped.
    for cond in conditions:
        enum_vals = cond.get("enum_values") or []
        if len(enum_vals) <= 2:
            continue
        covered = {str(cond["required_val"]).lower(), str(cond["flip_val"]).lower()}
        for extra_val in enum_vals:
            if extra_val.lower() in covered:
                continue
            covered.add(extra_val.lower())
            extra_inputs = [
                f"{c['name']}: {extra_val}" if c["name"] == cond["name"] else f"{c['name']}: {c['required_val']}"
                for c in conditions
            ]
            scenarios.append({
                "scenario_id":   sid(),
                "scenario_type": "edge",
                "hint_inputs":   extra_inputs,
                "hint_outcome":  f"{output_name} = {output_false} ({cond['name']} = {extra_val} is not a required-activation value)",
                "hint_objective": f"Verify {output_name} behaviour when {cond['name']} is set to its declared '{extra_val}' state (full Enum coverage)",
            })

    return scenarios


def _extract_nlp_context_for_queue(batch_index: int = 0, batch_size: int = 15) -> str:
    """
    Fetches the AI queue, runs the NLP module to extract structured context
    from each requirement, and returns that context for Claude AI to generate
    test cases from scratch.

    The NLP module's role is extraction only:
      - Requirement sentences (filtered by signal words)
      - Subject and action phrases per sentence
      - Module, requirement type, testing type, priority, methodology
      - Notes context (enum definitions, cross-references, sub-requirement links)

    Claude AI uses this structured context as INPUT to author all test case fields.
    """
    try:
        import urllib.request
        from document_ingestion import ingest_document
        from test_case_generator import (
            extract_requirement_sentences,
            extract_subject,
            extract_action,
            assign_testing_type,
            assign_methodology,
            assign_priority,
            assign_environment,
        )

        # Fetch queued chunks from React UI backend
        req = urllib.request.Request(
            f"{BACKEND_URL}/api/ai/queue",
            headers={"Accept": "application/json"},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())

        chunks = data.get("chunks", [])
        if not chunks:
            return json.dumps({
                "status":  "empty",
                "message": (
                    "No requirements queued. Upload an SRS in the React UI "
                    "at localhost:5173 and click 'Generate with Claude AI' first."
                ),
            })

        # ── Batch slicing ────────────────────────────────────────────────
        total_reqs    = len(chunks)
        batch_size    = max(1, batch_size)
        total_batches = max(1, (total_reqs + batch_size - 1) // batch_size)
        start         = batch_index * batch_size
        end           = min(start + batch_size, total_reqs)
        batch_chunks  = chunks[start:end]
        is_last_batch = (end >= total_reqs)
        # ─────────────────────────────────────────────────────────────────

        # Extract NLP context from each requirement chunk
        requirements_context = []

        for chunk_data in batch_chunks:
            req_id   = chunk_data.get("requirement_id", "REQ-001")
            content  = chunk_data.get("content", "")
            module   = chunk_data.get("module", "General")
            req_type = chunk_data.get("requirement_type", "functional")

            # Extract ONLY this requirement's text from the chunk content.
            # This prevents signals/values from sibling requirements polluting
            # the condition parsing for this specific requirement.
            req_content = _extract_req_content(req_id, content)
            prefixed = f"{req_id}: {req_content}"
            try:
                chunk_list = ingest_document(prefixed)
                if not chunk_list:
                    # Fallback: wrap as minimal chunk
                    from document_ingestion import DocumentChunk
                    chunk_list = [DocumentChunk(
                        requirement_ids=[req_id], content=content,
                        module=module, requirement_type=req_type,
                        is_sub_req=False, parent_id=None
                    )]

                # Keep ONLY the first chunk — ingest_document may produce
                # extra chunks when the body text contains cross-referenced
                # IDs (e.g. "see also MRJ_MCU_SRS_005"). Those extras are
                # not separate requirements and inflate the count from 11→18.
                chunk_list = chunk_list[:1]

                for chunk in chunk_list:
                    # Always use the req_id from the outer chunk_data entry
                    # (ingest may split or rename; we preserve the original)
                    chunk_req_id = req_id
                    sentences    = extract_requirement_sentences(chunk.content)
                    notes_ctx    = getattr(chunk, "notes_context", "")

                    sentence_contexts = []
                    for sentence in sentences:
                        testing_type = assign_testing_type(sentence, chunk.module)
                        environment  = assign_environment(testing_type)
                        subject      = extract_subject(sentence)
                        action       = extract_action(sentence)

                        # Compute priorities for all four scenario types
                        scenario_priorities = {
                            st: assign_priority(chunk.requirement_type, st, testing_type)
                            for st in ("normal", "boundary", "edge", "robustness")
                        }
                        # Compute methodologies for all four scenario types
                        scenario_methodologies = {
                            st: assign_methodology(sentence, st)
                            for st in ("normal", "boundary", "edge", "robustness")
                        }

                        sentence_contexts.append({
                            "sentence":             sentence,
                            "subject":              subject,
                            "action":               action,
                            "testing_type":         testing_type,
                            "test_environment":     environment,
                            "scenario_priorities":  scenario_priorities,
                            "scenario_methodologies": scenario_methodologies,
                        })

                    if sentence_contexts:
                        required_scenarios = _build_required_scenarios(
                            chunk_req_id, chunk.content, sentence_contexts
                        )
                        requirements_context.append({
                            "requirement_id":       chunk_req_id,
                            "module":               chunk.module,
                            "requirement_type":     chunk.requirement_type,
                            "is_sub_req":           chunk.is_sub_req,
                            "parent_id":            chunk.parent_id,
                            "notes_context":        notes_ctx,
                            "sentences":            sentence_contexts,
                            "required_scenarios":   required_scenarios,
                            "required_scenario_count": len(required_scenarios),
                        })

            except Exception:
                continue

        if not requirements_context:
            return json.dumps({"error": "NLP extraction produced no requirement context"})

        # ── Report estimated input tokens to the backend ──────────────────
        try:
            _resp_preview = json.dumps({"requirements": requirements_context})
            _report_req = urllib.request.Request(
                f"{BACKEND_URL}/api/tokens/report",
                data=json.dumps({
                    "direction": "input",
                    "chars": len(_resp_preview),
                    "session_id": data.get("session_id"),
                }).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(_report_req, timeout=5)
        except Exception:
            pass  # token reporting is best-effort, never block generation
        # ─────────────────────────────────────────────────────────────────

        return json.dumps({
            "status":             "ready",
            "batch_index":        batch_index,
            "total_batches":      total_batches,
            "is_last_batch":      is_last_batch,
            "batch_req_count":    len(requirements_context),
            "total_requirements": total_reqs,
            "requirements":       requirements_context,
            "schema": {
                "description": (
                    "Each requirement contains NLP-extracted context. "
                    "Use this context to generate test cases from scratch. "
                    "Generate one set of test cases per requirement, covering all four "
                    "scenario types: normal, boundary, edge, and robustness."
                ),
                "required_output_fields": [
                    "traceability_req_id  — use the requirement_id exactly as provided",
                    "test_case_id         — format: TC_VD_001 (validation), TC_IT_001 (integration), TC_UT_001 (verification); one ID per requirement",
                    "scenario_id          — format: SC_001, SC_002, ... reset per requirement",
                    "priority             — use scenario_priorities[scenario_type] from NLP context",
                    "module               — use module from NLP context exactly",
                    "requirement_type     — use requirement_type from NLP context (functional or non-functional)",
                    "scenario_type        — one of: normal | boundary | edge | robustness",
                    "testing_type         — use testing_type from NLP context (verification/validation/integration)",
                    "test_environment     — use test_environment from NLP context (Dev/QA/UAT/Prod)",
                    "design_methodology   — use scenario_methodologies[scenario_type] from NLP context",
                    "dependent_test_cases — 'None' for SC_001 (normal); 'TC_XX_NNN_SC-001' for all others",
                    "inputs               — list of strings in 'SignalName: Value' format (e.g. 'Tail Low Condition: True')",
                    "objective            — clear, specific statement of what is being verified; no modal verbs (shall/must/can/will)",
                    "preconditions        — list of strings: specific, testable conditions that must be true before execution",
                    "test_steps           — list of strings: numbered, actionable steps (e.g. '1. Navigate to ...')",
                    "expected_outcome     — MUST start with 'ActualSignalName = Value. ' using the REAL output signal name "
                                           "extracted from the requirement (e.g. 'Altitude Alert Condition Enabled = True. '). "
                                           "For normal/boundary scenarios the value is True/Enabled/Active; "
                                           "for edge/robustness scenarios the value is False/Disabled/Inactive. "
                                           "Never use generic placeholders like 'Output signal' or 'output'.",
                    "remarks              — risk, compliance, ambiguity, or coverage observations relevant to this scenario",
                ],
                "generation_rules": [
                    "Use the sentence, subject, and action from NLP context to author each field",
                    "required_scenarios gives you the EXACT list — generate one TC per entry; do NOT skip any",
                    "required_scenario_count tells you the total; your output MUST match that count",
                    "Copy the scenario_id from required_scenarios entry exactly (SC_001, SC_002...)",
                    "Use hint_inputs as the starting point for the inputs field",
                    "Use hint_outcome as the starting point for expected_outcome",
                    "Use hint_objective as the starting point for objective",
                    "Complete ALL other required fields (preconditions, test_steps, remarks, etc.)",
                    "No modal verbs (shall/must/can/will) anywhere in objective, steps, or expected_outcome",
                    "test_steps must be an array of numbered strings: ['1. Do X', '2. Do Y']",
                    "preconditions must be an array of strings",
                    "inputs MUST include EVERY input signal for EVERY scenario — even signals that are not being varied must be listed with their nominal value. A scenario with 3 input signals must always have 3 entries in inputs. NEVER leave any signal out of the inputs array",
                    "expected_outcome MUST begin with 'RealSignalName = True/False. ' — extract the output signal name from the requirement sentence itself; do NOT use 'output', 'Output signal', or any generic placeholder",
                    "If notes_context is present, incorporate enum definitions or cross-references into remarks",
                    "For sub-requirements (is_sub_req=true), reference parent_id in dependent_test_cases for the normal scenario",
                    "After generating all test cases, call save_enhanced_test_cases with the complete list",
                ],
            },
        }, indent=2)

    except Exception as e:
        return json.dumps({"error": f"NLP extraction failed: {str(e)}"})


def _save_enhanced_cases(test_cases: list, is_partial: bool = False) -> str:
    """
    Saves test cases incrementally (is_partial=True per batch)
    or as a final save (is_partial=False, default).
    Keeps each MCP payload small to avoid the 1MB limit.
    """
    try:
        import urllib.request

        if not test_cases:
            return json.dumps({"error": "No test cases provided"})

        # ── Report estimated output tokens ───────────────────────────────
        try:
            _tc_preview = json.dumps(test_cases)
            _report_req = urllib.request.Request(
                f"{BACKEND_URL}/api/tokens/report",
                data=json.dumps({
                    "direction": "output",
                    "chars": len(_tc_preview),
                }).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(_report_req, timeout=5)
        except Exception:
            pass
        # ───────────────────────────────────────────────────────────────

        # Send this batch to the backend chunk buffer
        chunk_payload = json.dumps({
            "test_cases": test_cases,
            "is_last": not is_partial,
        }).encode("utf-8")
        chunk_req = urllib.request.Request(
            f"{BACKEND_URL}/api/mcp/save_chunk",
            data=chunk_payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(chunk_req, timeout=120)

        if is_partial:
            # More batches coming — just acknowledge
            return json.dumps({
                "status": "partial_saved",
                "message": f"{len(test_cases)} test cases buffered. Continue with next batch.",
            })

        # Final batch — merge all chunks and mark complete
        fin_req = urllib.request.Request(
            f"{BACKEND_URL}/api/mcp/save_finalise",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(fin_req, timeout=120)

        done_req = urllib.request.Request(
            f"{BACKEND_URL}/api/ai/complete",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(done_req, timeout=60)

        return json.dumps({
            "status": "saved",
            "message": "All test cases saved. Click Load Results in the tool.",
        })

    except Exception as e:
        return json.dumps({
            "error": f"Save failed: {str(e)}",
            "tip": "Retry save_enhanced_test_cases — your generated test cases are not lost.",
        })


def _extract_and_generate_single(req_text: str, req_id: str, module: str) -> str:
    """
    Extracts NLP context from a single requirement typed in chat and returns
    it for Claude AI to generate test cases from scratch.
    Results are saved to the React UI after generation.
    """
    try:
        from document_ingestion import ingest_document
        from test_case_generator import (
            extract_requirement_sentences,
            extract_subject,
            extract_action,
            assign_testing_type,
            assign_methodology,
            assign_priority,
            assign_environment,
        )

        prefixed = f"{req_id} {req_text}"
        chunks   = ingest_document(prefixed)
        if not chunks:
            return json.dumps({"error": "No requirement chunks detected"})

        requirements_context = []

        for chunk in chunks:
            chunk_req_id = chunk.requirement_ids[0] if chunk.requirement_ids else req_id
            sentences    = extract_requirement_sentences(chunk.content)
            notes_ctx    = getattr(chunk, "notes_context", "")

            sentence_contexts = []
            for sentence in sentences:
                testing_type = assign_testing_type(sentence, chunk.module)
                environment  = assign_environment(testing_type)
                subject      = extract_subject(sentence)
                action       = extract_action(sentence)

                scenario_priorities = {
                    st: assign_priority(chunk.requirement_type, st, testing_type)
                    for st in ("normal", "boundary", "edge", "robustness")
                }
                scenario_methodologies = {
                    st: assign_methodology(sentence, st)
                    for st in ("normal", "boundary", "edge", "robustness")
                }

                sentence_contexts.append({
                    "sentence":               sentence,
                    "subject":                subject,
                    "action":                 action,
                    "testing_type":           testing_type,
                    "test_environment":       environment,
                    "scenario_priorities":    scenario_priorities,
                    "scenario_methodologies": scenario_methodologies,
                })

            if sentence_contexts:
                requirements_context.append({
                    "requirement_id":   chunk_req_id,
                    "module":           chunk.module,
                    "requirement_type": chunk.requirement_type,
                    "is_sub_req":       chunk.is_sub_req,
                    "parent_id":        chunk.parent_id,
                    "notes_context":    notes_ctx,
                    "sentences":        sentence_contexts,
                })

        if not requirements_context:
            return json.dumps({"error": "NLP extraction produced no context for this requirement"})

        return json.dumps({
            "status": "ready",
            "total_requirements": len(requirements_context),
            "requirements": requirements_context,
            "schema": {
                "description": (
                    "NLP-extracted context for a single requirement. "
                    "Generate test cases from scratch using this context, "
                    "covering normal, boundary, edge, and robustness scenario types. "
                    "After generating, call save_enhanced_test_cases with the complete list."
                ),
                "required_output_fields": [
                    "traceability_req_id, test_case_id, scenario_id, priority, module, "
                    "requirement_type, scenario_type, testing_type, test_environment, "
                    "design_methodology, dependent_test_cases, inputs, objective, "
                    "preconditions, test_steps, expected_outcome, remarks"
                ],
                "generation_rules": [
                    "Use sentence/subject/action from NLP context to author each field",
                    "No modal verbs (shall/must/can/will) in objective, steps, or expected_outcome",
                    "test_steps: array of numbered strings ['1. ...', '2. ...']",
                    "preconditions: array of strings",
                    "inputs: array of strings in 'SignalName: Value' format using actual signal names from the requirement",
                    "expected_outcome MUST start with 'RealSignalName = True/False. ' using the actual output signal name from the requirement — never use 'output', 'Output signal', or any generic placeholder",
                    "For normal/boundary scenarios the output value is True/Enabled/Active; for edge/robustness it is False/Disabled/Inactive",
                    "dependent_test_cases: 'None' for SC_001, 'TC_XX_NNN_SC-001' for others",
                    "After generating, call save_enhanced_test_cases",
                ],
            },
        }, indent=2)

    except Exception as e:
        return json.dumps({"error": str(e)})


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options()
        )


if __name__ == "__main__":
    asyncio.run(main())