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
                "Extracts structured NLP context from the uploaded SRS document and "
                "returns it as input for Claude AI to generate test cases from scratch. "
                "The NLP module identifies requirement sentences, subjects, actions, "
                "testing types, priorities, and methodologies for each requirement — "
                "Claude AI uses this context to author all test case fields. "
                "After generating, call save_enhanced_test_cases with the complete list."
            ),
            inputSchema={"type": "object", "properties": {}}
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
        loop   = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, _extract_nlp_context_for_queue)

    elif name == "save_enhanced_test_cases":
        test_cases = arguments.get("test_cases", [])
        loop       = asyncio.get_event_loop()
        result     = await loop.run_in_executor(
            None, _save_enhanced_cases, test_cases
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

def _extract_nlp_context_for_queue() -> str:
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

        # Extract NLP context from each requirement chunk
        requirements_context = []

        for chunk_data in chunks:
            req_id   = chunk_data.get("requirement_id", "REQ-001")
            content  = chunk_data.get("content", "")
            module   = chunk_data.get("module", "General")
            req_type = chunk_data.get("requirement_type", "functional")

            prefixed = f"{req_id} {content}"
            try:
                chunk_list = ingest_document(prefixed)
                if not chunk_list:
                    continue

                for chunk in chunk_list:
                    chunk_req_id = chunk.requirement_ids[0] if chunk.requirement_ids else req_id
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
                        requirements_context.append({
                            "requirement_id":   chunk_req_id,
                            "module":           chunk.module,
                            "requirement_type": chunk.requirement_type,
                            "is_sub_req":       chunk.is_sub_req,
                            "parent_id":        chunk.parent_id,
                            "notes_context":    notes_ctx,
                            "sentences":        sentence_contexts,
                        })

            except Exception:
                continue

        if not requirements_context:
            return json.dumps({"error": "NLP extraction produced no requirement context"})

        return json.dumps({
            "status": "ready",
            "total_requirements": len(requirements_context),
            "requirements": requirements_context,
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
                    "Generate four test cases per requirement sentence: normal, boundary, edge, robustness",
                    "No modal verbs (shall/must/can/will) anywhere in objective, steps, or expected_outcome",
                    "test_steps must be an array of numbered strings: ['1. Do X', '2. Do Y']",
                    "preconditions must be an array of strings",
                    "inputs must be an array of strings in 'SignalName: Value' format using the actual signal names from the requirement",
                    "expected_outcome MUST begin with 'RealSignalName = True/False. ' — extract the output signal name from the requirement sentence itself; do NOT use 'output', 'Output signal', or any generic placeholder",
                    "If notes_context is present, incorporate enum definitions or cross-references into remarks",
                    "For sub-requirements (is_sub_req=true), reference parent_id in dependent_test_cases for the normal scenario",
                    "After generating all test cases, call save_enhanced_test_cases with the complete list",
                ],
            },
        }, indent=2)

    except Exception as e:
        return json.dumps({"error": f"NLP extraction failed: {str(e)}"})


def _save_enhanced_cases(test_cases: list) -> str:
    """
    Saves Claude's AI-generated test cases to the React UI.
    """
    try:
        import urllib.request
        from collections import Counter

        if not test_cases:
            return json.dumps({"error": "No test cases provided"})

        summary = {
            "total":               len(test_cases),
            "duplicates_removed":  0,
            "by_module":           dict(Counter(tc.get("module", "General") for tc in test_cases)),
            "by_requirement_type": dict(Counter(tc.get("requirement_type", "functional") for tc in test_cases)),
            "by_scenario_type":    dict(Counter(tc.get("scenario_type", "normal") for tc in test_cases)),
            "by_testing_type":     dict(Counter(tc.get("testing_type", "verification") for tc in test_cases)),
            "by_priority":         dict(Counter(tc.get("priority", "P1") for tc in test_cases)),
        }

        payload = json.dumps({
            "test_cases": test_cases,
            "summary":    summary,
        }).encode("utf-8")

        # Save to React UI
        save_req = urllib.request.Request(
            f"{BACKEND_URL}/api/mcp/save",
            data    = payload,
            headers = {"Content-Type": "application/json"},
            method  = "POST",
        )
        urllib.request.urlopen(save_req, timeout=10)

        # Mark queue complete
        done_req = urllib.request.Request(
            f"{BACKEND_URL}/api/ai/complete",
            data    = b"{}",
            headers = {"Content-Type": "application/json"},
            method  = "POST",
        )
        urllib.request.urlopen(done_req, timeout=10)

        return json.dumps({
            "status":  "saved",
            "total":   len(test_cases),
            "message": (
                f"All {len(test_cases)} AI-generated test cases saved to React UI. "
                f"Open http://localhost:5173 — the results banner will appear."
            ),
        }, indent=2)

    except Exception as e:
        return json.dumps({"error": f"Save failed: {str(e)}"})


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