"""
src/orchestrator/llm_openai.py

OpenAI client wrapper for function calling.
- call_model(): one shot (no tool execution)
- call_with_tools(): iterative loop that executes tool calls and feeds results back
"""


import os
import json
from typing import Any, Dict, List, Optional
from openai import OpenAI


client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

Default_Model = os.getenv("OPENAI_MODEL", "gpt-40-mini")


def call_model(messages: List[Dict[str, Any]], tools: Optional[List[Dict[str, Any]]] = None):
    """
    Low-level call to OpenAI Chat Completions with optional tool specs.
    Returns the raw response object.
    """

    resp = client.chat.completions.create(
        model=DEFAULT_MODEL,
        messages=messages,
        tools=tools or None,
        tool_choice="auto" if tools else "none",
        temperature=0.2
    )

    return resp


def extract_tool_calls(choice) -> List[Dict[str, Any]]:
    """
    Normalize tool calls from the OpenAI response choice.
    """

    out = []
    tcs = getattr(choice.message, "tool_calls", None)

    if not tcs:
        return out
    
    for tc in tcs:
        if tc.type == "function" and tc.function:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
            except Exception:
                args = {}
            out.append({"name": name, "arguments": args, "id": tc.id})

    return out