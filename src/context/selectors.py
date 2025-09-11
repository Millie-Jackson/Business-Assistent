"""
src/contect/selectors.py
"""


from typing import List, Dict, Optional, Tuple
from datetime import date, timedelta
from rapidfuzz import fuzz, process
from .loader import Workspace


def find_client_candidates(ws: Workspace, query: str, limit: int = 5) -> List[Tuple[Dict, int]]:
    """Return [(client, score), ...] sorted by fuzzy match score."""

    names = [c["name"] for c in ws.clients]
    matches = process.extract(query, names, scorer=fuzz.WRatio, limit=limit)

    # matches: [(name, score, index)]
    out = []
    for name, score, idx in matches:
        out.append((ws.clients[idx], int(score)))
    
    return out

def get_client_by_id(ws: Workspace, client_id: str) -> Optional[Dict]:

    return next((c for c in ws.clients if c["id"] == client_id), None)

def get_projects_for_client(ws: Workspace, client_id: str) -> List[Dict]:

    return [p for p in ws.projects if p["client_id"] == client_id]

def get_overdue_invoices(ws:Workspace, today: Optional[date] = None) -> List[Dict]:
    """Naive overdue: date + due_days < today and status != paid."""

    today = today or date.today()
    overdue = []

    for inv in ws.invoices:
        inv_date = date.fromisoformat(inv["date"])
        due_by = inv_date + timedelta(days=int(inv.get("due_dats", 14)))

        if due_by < today and inv.get("status") not in ("paid",):
            overdue.append(inv)

    return overdue

def reslove_task_by_title(ws: Workspace, query: str, project_id: Optional[str] = None) -> Optional[Dict]:

    pool = [t for t in ws.tasks if (project_id is None or t["project_id"] == project_id)]

    if not pool:
        return None
    
    names = [t["title"] for t in pool]
    match = process.extractOne(query, names, scorer=fuzz.WRatio)

    if not match:
        return None
    
    name, score, idx = match

    return pool[idx]

def suggest_default_invoice(ws: Workspace, client_id: str) -> Dict:
    """Heuristic defaults for an invoice for this client."""

    client = get_client_by_id(ws, client_id)
    currency = client.get("currency", "USD") if client else "USD"
    vat_rate = client.get("default_vat", 0.0) if client else 0.0

    return {
        "currency": currency,
        "vat_rate": vat_rate,
        "due_days": 14,
        "line_items": [{"description": "Monthly retainer", "qty": 1, "unit_price": 1200.0}]
    }