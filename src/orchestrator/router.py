"""
src/orchestrator/router.py

Router: builds tool specs, runs the function-calling loop, executes tools, and returns a tidy result.
"""


import json
from typing import Any, Dict, List, Optional, Callable
from datetime import datetime

from orchestrator.llm_openai import call_model, extract_tool_calls
from orchestrator.models import ToolCall, ToolResult, AuditEntry, OrchestratorResult
from orchestrator import prompts
from config import DEFAULT_CURRENCY, DEFAULT_PERSONA
from tools import crm, projects, ops


# -------- Tool registry (name -> callable, schema) -----------------------------


def _tool_spec(name: str, description: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
    """Build an OpenAI function spec."""

    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": parameters.get("properties", {}),
                "required": parameters.get("required", []),
                "additionalProperties": False,
            },
        },
    }

def get_tools_and_specs() -> List[Dict[str, Any]]:
    """
    JSON schemas describing the tools we expose to the model.
    Keep them small and typed to reduce hallucinations.
    """

    return [
        _tool_spec(
            "find_client",
            "Find best-matching clients for a free-text query.",
            {
                "properties": {
                    "query": {"type": "string"},
                    "top_k": {"type": "integer", "default": 5}
                },
                "required": ["query"]
            }
        ),
        _tool_spec(
            "create_invoice",
            "Create a draft invoice for a client.",
            {
                "properties": {
                    "user_role": {"type": "string", "enum": ["owner", "manager", "member", "viewer"]},
                    "client_id": {"type": "string"},
                    "currency": {"type": "string", "enum": ["USD", "GBP", "EUR"]},
                    "vat_rate": {"type": "number"},
                    "line_items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "description": {"type": "string"},
                                "qty": {"type": "number"},
                                "unit_price": {"type": "number"}
                            },
                            "required": ["description", "qty", "unit_price"],
                            "additionalProperties": False
                        }
                    },
                    "due_days": {"type": "integer", "default": 14},
                    "notes": {"type": "string"}
                },
                "required": ["user_role", "client_id", "currency", "vat_rate", "line_items"]
            }
        ),
        _tool_spec(
            "chase_late_payers",
            "Find overdue invoices and draft polite reminder messages.",
            {
                "properties": {
                    "user_role": {"type": "string", "enum": ["owner", "manager", "member", "viewer"]}
                },
                "required": ["user_role"]
            }
        ),
        _tool_spec(
            "list_tasks",
            "List tasks for a project.",
            {
                "properties": {
                    "project_id": {"type": "string"},
                    "status": {"type": "string", "enum": ["todo", "doing", "done"]}
                },
                "required": ["project_id"]
            }
        ),
        _tool_spec(
            "create_task",
            "Create a new task in a project.",
            {
                "properties": {
                    "user_role": {"type": "string", "enum": ["owner", "manager", "member", "viewer"]},
                    "project_id": {"type": "string"},
                    "title": {"type": "string"},
                    "assignee_user_id": {"type": "string"},
                    "due_date": {"type": "string"}
                },
                "required": ["user_role", "project_id", "title"]
            }
        ),
        _tool_spec(
            "move_task",
            "Move a task to a new status.",
            {
                "properties": {
                    "user_role": {"type": "string", "enum": ["owner", "manager", "member", "viewer"]},
                    "task_query_or_id": {"type": "string"},
                    "new_status": {"type": "string", "enum": ["todo", "doing", "done"]},
                    "project_id": {"type": "string"}
                },
                "required": ["user_role", "task_query_or_id", "new_status"]
            }
        ),
        _tool_spec(
            "record_expense",
            "Record an operational expense.",
            {
                "properties": {
                    "user_role": {"type": "string", "enum": ["owner", "manager", "member", "viewer"]},
                    "amount": {"type": "number"},
                    "currency": {"type": "string", "enum": ["USD", "GBP", "EUR"]},
                    "description": {"type": "string"},
                    "date_iso": {"type": "string"},
                    "category": {"type": "string"},
                    "project_id": {"type": "string"},
                    "client_id": {"type": "string"},
                    "persona": {"type": "string", "enum": ["PA", "Accountant", "Intern"]}
                },
                "required": ["user_role", "amount", "currency", "description"]
            }
        ),
        _tool_spec(
            "weekly_summary",
            "Summarise a week (expenses, invoices, payments).",
            {
                "properties": {
                    "start_date": {"type": "string"},
                    "end_date": {"type": "string"}
                },
                "required": []
            }
        ),
    ]


# -------- Tool execution bridge ------------------------------------------------
def _execute_tool(name: str, args: Dict[str, Any]) -> ToolResult:
    """Map a tool call name to our Python functions and execute."""

    try:
        if name == "find_client":
            out = crm.find_client(**args)
        elif name == "creative_invoice":
            out = crm.create_invoice(**args)
        elif name == "chase_late_payers":
            out = crm.chase_late_payers(**args)
        elif name == "list_tasks":
            out = projects.create_task(**args)
        elif name == "create_task":
            out = projects.create_task(**args)
        elif name == "move_task":
            out = projects.move_task(**args)
        elif name == "record_expenses":
            out = ops.record_expenses(**args)
        elif name == "weekly_summary":
            out = ops.weekly_summary(**args)
        else:
          return ToolResult(name=name, ok=False, output=None, error=f"Unknown tool: {name}")
        return ToolResult(name=name, ok=True, output=out)
    except Exception as e:
        return ToolResult(name=name, ok=False, output=None, error=str(e))
    

# -------- Orchestrate ----------------------------------------------------------
def run(user_text: str, *, persona: str = None, currency: str = None, extra_context: Optional[Dict[str, Any]] = None, max_tootl_rounds: int = 3) -> OrchestratorResult:
    """
    Entry point: takes the raw user_text plus UI settings, runs a tool-calling loop, returns a tidy result.
    """

    persona = persona or DEFAULT_PERSONA.value
    currency = currency or DEFAULT_CURRENCY.value

    system_prompt = prompts.SYSTEM_TEMPLATE.get(persona, prompts.SYSTEM_TEMPLATE["PA"])

    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "system", "content": f"Default currency: {currency}. Keep answers concise."},
        {"role": "user", "content": user_text.strip()},
    ]

    tool_specs = get_tools_and_specs()
    audit: List[AuditEntry] = []

    for round_idx in range(max_tool_rounds):
        resp = call_model(messages, tools=tool_specs)
        choice = resp.choices[0]
        tool_calls = extract_tool_calls(choice)

        # If the model returned a normal message and no tool calls, we are done
        if not tool_calls:
            final_text = choice.message.content or "(no content)"
            audit.append(AuditEntry(step=f"model_round_{round_idx+1}", ok=True, detail="No tool call: returning text."))
            return OrchestratorResult(summary=final_text, messages=messages + [choice.message.model_dump()], audit=audit)
        
        # Execute each tool call in order, feed back results
        for tc_raw in tool_calls:
            tc = ToolCall(name=tc_raw["name"], arguments=tc_raw.get("arguments", {}))
            audit.append(AuditEntry(step="tool_call", ok=True, detail=f"Calling {tc.name}", tool_call=tc))
            result = _execute_tool(tc.name, tc.arguments)
            audit.append(AuditEntry(step="tool_result", ok=result.ok, detail=("ok" if result.ok else result.error or "error"), tool_call=tc, tool_result=result))

            # Push tool result back to the model as a special "tool" message
            messages.append({
                "role": "tool",
                "tool_call_id": tc_raw.get("id"),
                "name": tc.name,
                "content": json.dumps(result.model_dump(), ensure_ascii=False)
            })
    # Safety stop: if we hit max rounds without final text, ask model to summarise
    resp = call_model(messages, tools=None)
    final_text = resp.choice[0].message.content or "(no content)"
    audit.append(AuditEntry(step="max_rounds_reached", ok=True, detail="Stopped after max rounds; summerised."))

    return OrchestratorResult(summary=final_text, messages=messages + [resp.choice[0].message.model_dump()], audit=audit)