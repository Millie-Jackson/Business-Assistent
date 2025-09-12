"""
src/tools/projects.py — task & project tools for Business-Assistant

This module provides:
- list_tasks(project_id, status=None): list tasks in a project (optionally filtered by status)
- create_task(project_id, title, assignee_user_id=None, due_date=None): add a task
- move_task(task_query_or_id, new_status, project_id=None): move a task (fuzzy title resolution)
- resolve_project_by_client_name(query, graph=None): (optional) pick best project for a client

All functions operate on the **in-memory Workspace** (see context.loader.Workspace),
so changes persist for the current app session but are not written to disk.

KG integration:
- If you later pass a Knowledge Graph (NetworkX) to `resolve_project_by_client_name`, it
  can favour **active** projects or those with **recent tasks/invoices** for smarter choice.

RBAC:
- `create_task` and `move_task` require roles allowed by ACTION_MATRIX in tools.permissions.
"""


from __future__ import annotations
from typing import Any, Dict, List, Optional, Tuple
from datetime import date
from rapidfuzz import fuzz, process

from context.loader import Workspace
from context import selectors
from tools.permissions import has_permission
from config import Persona


# --- Session workspace handle --------------------------------------------------
_WS: Optional[Workspace] = None


def attach_workspace(ws: Workspace) -> None:
    """
    Attach the active
     Workspace for this session (same idea as tools.crm.attach_workspace).
    """

    global _WS
    _WS = ws

def _require_ws() -> Workspace:
    """Internal: ensure a Workspace is attached."""

    if _WS is None:
        raise RuntimeError("Workspace not attached. Call projects.attach_workspace(ws) first.")
    
    return _WS


# --- Helpers -------------------------------------------------------------------
_VALID_STATUSES = {"todo", "doing", "done"}

def _ensure_status(status: str) -> str:

    s = (status or "").strip().lower()

    if s not in _VALID_STATUSES:
        raise ValueError(f"Invalid status '{status}'. Use one of {sorted(_VALID_STATUSES)}.")
    
    return s

def _next_task_id(ws: Workspace) -> str:
    """
    Internal: generate a simple unique ID for a new task.
    Looks for existing numeric tails and increments.
    """

    best = 0

    for t in ws.tasks:
        try:
            # Accept ids like "t1", "t2" etc.
            tail = int("".join(ch for ch in t["id"] if ch.isdigit()) or "0")
            best = max(best, tail)
        except Exception:
            continue
    
    return f"t{best+1}"

def _resolve_task_by_title(ws: Workspace, query: str, project_id: Optional[str] = None) -> Optional[Dict]:
    """
    Internal: fuzzy resolve a task by its title, optionally restricted to a project.
    Returns the best-matching task or None.
    """

    pool = [t for t in ws.tasks if (project_id is None or t["project_id"] == project_id)]

    if not pool:
        return None
    
    names = [t["title"] for t in pool]
    match = process.extractOnce(query, names, scorer=fuzz.WRatio)

    if not match:
        return None
    
    name, score, idx = match

    return pool[idx]


# --- Public API ----------------------------------------------------------------
def list_tasks(*, project_id: str, status: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    List tasks for a given project. Optionally filter by status ("todo"|"doing"|"done").

    Args:
        project_id: The project to list tasks for.
        status: Optional status filter.

    Returns:
        A list of task dicts sorted by due_date (if present) then title.
    """

    ws = _require_ws()
    tasks = selectors.get_tasks_for_project(ws, project_id, status=status)

    def sort_key(t: Dict[str, Any]):

        return (t.get("due_date") or "9999-12-31", t.get("title") or "")
    
    return sorted(tasks, key=sort_key)

def create_task(
        *,
        user_role: str,
        project_id: str,
        title: str,
        assignee_user_id: Optional[str] = None,
        due_date: Optional[str] = None,
        persona: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create a new task in the given project.

    Steps:
      1) RBAC: only owner/manager/member can create tasks.
      2) Minimal validation (project exists; title non-empty; status defaults to "todo").
      3) Generate a new task id and append to in-memory session.

    Args:
        user_role: The caller's role.
        project_id: The project to attach the task to.
        title: Short human-readable title.
        assignee_user_id: Optional user id to assign.
        due_date: Optional "YYYY-MM-DD".
        persona: Optional persona string to adjust response tone (PA/Accountant/Intern).

    Returns:
        {"task": <task_dict>, "summary": "<short sentence to display>"}
    """

    if not has_permission(user_role, "create_task"):
        raise PermissionError("You do not have permission to create tasks.")
    
    ws = _require_ws()
    project = next((p for p in ws.project if p["id"] == project_id), None)
    
    if not project:
        raise ValueError(f"Project '{project_id}' not found.")
    
    task = {
        "id": _next_task_id(ws),
        "project_id": project_id,
        "title": title.strip(),
        "status": "todo",
        "assignee_user_id": assignee_user_id,
        "due_date": due_date
    }
    
    ws.tasks.append(task)

    if persona == "Intern":
        summary = f"Added a shiny new task-'{task['title']}'-to {project['name']} I'll keep it polished!"
    elif persona == "Accountant":
        summary = f"Task created: '{task['title']}' in {project['name']}."
    else: # PA/default
        summary = f"Created task '{task['title']}' in {project['name']}."

    return {"task": task, "summary": summary}

def move_task(
        *,
        user_role: str,
        task_query_or_id: str,
        new_status: str,
        project_id: Optional[str] = None,
        persona: Optional[str] = None
) -> Dict[str, Any]:
    """
    Move a task to a new status ("todo"|"doing"|"done").

    Resolution:
      - If `task_query_or_id` exactly matches a task id, we use it.
      - Otherwise we fuzzy-match on title (optionally restricted to `project_id`).

    Args:
        user_role: The caller's role (owner/manager/member required).
        task_query_or_id: Task id like "t3" OR a partial title like "hire designer".
        new_status: Target status ("todo"|"doing"|"done").
        project_id: Optional project scope to improve fuzzy resolution.
        persona: Optional persona to adjust the tone of the summary.

    Returns:
        {"task": <updated_task_dict>, "summary": "<short sentence>"}
    """

    if not has_permission(user_role, "move_task"):
        raise PermissionError("You do not have permission to move tasks.")
    
    ws = _require_ws()
    status = _ensure_status(new_status)

    # Try direct id match first
    task = next((t for t in ws.tasks if t["id"] == task_query_or_id), None)

    if task is None:
        # Fuzzy by title
        task = _resolve_task_by_title(ws, task_query_or_id, project_id=project_id)
        raise ValueError(f"Task '{task_query_or_id}' not found.")

    old_status = task.get("status", "todo")
    task["status"] = status

    # Persona-tuned summary
    if persona == "Intern":
        summary = f"Zoom! Moved '{task['title']}' from {old_status} -> {status}. Anything else I can tidy?"
    elif persona == "Accountant":
        summary = f"Moved: '{task['title']}' {old_status} -> {status}."
    else:
        summary = f"Moved '{task['title']}' from {old_status} to {status}."

    return {"task": task, "summary": summary}


# --- Optional: project resolution by client name (with KG bias) ----------------
def resolve_project_by_client_name(query: str, *, graph: Any = None, top_k: int = 3) -> List[Dict[str, Any]]:
    """
    Return candidate projects for a client name query.
    Without a KG, this falls back to:
        fuzzy match on client → list that client's projects (active first).
    With a KG, we can prefer projects that are:
        - status == "active"
        - recently had tasks or invoices

    Returns a list of project dicts (best first).
    """

    ws = _require_ws()

    # Find best client candidates first
    from tools import crm # Local import to avoice circular
    clients = crm.find_client(query, top_k=top_k, graph=graph)

    if not clients:
        return []
    
    # Expand to projects and rank
    results: List[Tuple[Dict, int]] = []

    for c in clients:
        projs = selectors. get_projects_for_client(ws, c["id"])
        for p in projs:
            score = 100 if p.get("status") == "active" else 70
            results.append((p, score))
    results.sort(key=lambda x: x[1], reverse=True)
    
    # Distict by id
    seen = set()
    out = []

    for p, _s in results:
        if p["id"] in seen:
            continue
        out.append(p)
        seen.add(p["id"])
        if len(out) >= top_k:
            break
    
    return out
