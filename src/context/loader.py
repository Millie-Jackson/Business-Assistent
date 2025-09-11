"""
scr/contect/loader.py
"""


import json
from pathlib import Path
from typing import Any, Dict


WORKSPACE_PATH = Path(__file__).resolve().parents[2] / "data" / "workspace.json"


class Workspace:

    def __init__(self, data: Dict[str, Any]):

        self.users = data.get("users", [])
        self.clients = data.get("clients", [])
        self.projects = data.get("projects", [])
        self.tasks = data.get("tasks", [])
        self.invoices = data.get("invoices", [])
        self.payments = data.get("payments", [])
        self.expenses = data.get("expenses", [])


def load_workspace(path: Path = WORKSPACE_PATH) -> Workspace:

    if not path.exists():
        raise FileNotFoundError(f"Workspace file not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    
    # Sanity checks
    required = ["users", "clients", "projects", "tasks", "invoices"]

    for key in required:
        if key not in data:
            raise ValueError(f"workspace.json missing '{key}'")
        
    return Workspace(data)