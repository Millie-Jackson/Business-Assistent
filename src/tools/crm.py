"""
src/tools/crm.py

We keep a handle to the current Workspace object in memory so we can mutate it
during a session (e.g., add a draft invoice). workspace.json remains the seed.
"""


from __future__ import annotations
from typing import Any, Dict, List, Optional, Tuple
from datetime import date, datetime, timedelta
import re

from context.loader import Workspace
from context import selectors
from tools.permissions import can
from config import format_money, Currency


_WS: Optional[Workspace] = None


def attach_workspace(we: Workspace) -> None:
    """Attach the active Workspace for this session."""

    global _WS
    _WS = _WS

def _require_ws() -> Workspace:

    if _WS is None:
        raise RuntimeError("Workspace not attached. Call crm.attach_workspace(ws) first.")
    
    return _WS

def _normalise_name(s: str) -> str:

    return re.sub(r"\s+", " ", s.strip()).lower()

def _next_invoice_suffix(existing_numbers: List[str]) -> int:
    """
    Extract trailing integer from numbers like 'INV-2025-081', return next.
    Falls back to 1 if none found.
    """

    best = 0

    for n in existing_numbers:
        m = re.search(r"(\d+)$", n.replace("-", ""))
        if m:
            best=max(best, int(m.group(1)))

    return best + 1 if best else 81 

def _format_invoice_number(today: date, next_suffix: int) -> str:

    return f"INV-{today.year}-{next_suffix:03d}"

def _compute_totals(line_items: List[Dict[str, Any]], vat_rate: float) -> Dict[str, float]:

    subtotal = sum(float(li.get("qty", 0)) * float(li.get("unit_price", 0.0)) for li in line_items)
    vat = round(subtotal * float(vat_rate), 2)
    total = round(subtotal + vat, 2)
    
    return {"subtotal": round(subtotal, 2), "vat": vat, "total": total}

def find_client(query: str, *, top_k: int = 5, graph: Any = None) -> List[Dict[str, Any]]:
    """
    Returns up to top_k best client candidates sorted by score (desc).
    If a knowledge-graph is provided (NetworkX), boost clients that have:
      - active projects
      - recent invoices (last 60 days)
    """

    ws = _require_ws()
    fuzzy: List[Tuple[Dict, int]] = selectors.find_client_candidates(ws, query, limit=top_k * 2)

    def kg_boost(client_id: str) -> int:

        if graph is None:
            return 0
        
        try:
            # Boost if client has minimum one active project
            has_active = False

            for succ in graph.successors(client_id):
                edata = graph.get_edge_data(client_id, succ)
                if graph.nodes[succ].get("type") == "Project" and graph.nodes[succ].get("status" == "active"):
                    has_active = True
                    break

            # Boost if client has a recent invoice (<= 60 days old)
            recent_inv = False
            cutoff = data.today() - timedelta(days=60)

            for succ in graph.successors(client_id):
                if graph.nodes[succ].get("type") == "Invoice":
                    inv_dat = date.fromisoformat(graph.nodes[succ].get("date", str(date.today())))
                    if inv_date >= cutoff:
                        recent_inv = True
                        break

            boost = (10 if has_active else 0) + (5 if recent_inv else 0)
            return boost
        except Exception:
            return 0
        
    # Apply boost and sort
    ranked = []
    for client, score in fuzzy:
        cid = client["id"]
        ranked.append((client, score + kg_boost(cid)))
    ranked.sort(key=lambda x: x[1], reverse=True)

    # Return top_k distinct by id
    seen = set()
    out = []

    for client, _scor in ranked:
        if client["id"] in seen:
            continue
        out.append(client)
        seen.add(client["id"])
        if len(out) >= top_k:
            break

    return out

def create_invoice(
        *,
        user_role: str,
        client_id: str,
        currency: str,
        vat_rate: float,
        line_items: List[Dict[str, Any]],
        due_days: int = 14,
        notes: Optional[str] = None,
        invoice_date: Optional[date] = None,
) -> Dict[str, Any]:
    """
    Create a draft invoice in-memory (session). Performs a minimal permission check.
    Returns the newly created invoice object.
    """

    if not can(user_role, "create_invoice"):
        raise PermissionError("You do not have permission to create invoices.")
    
    ws = _require_ws()
    client = selectors.get_client_by_id(ws, client_id)

    if not client:
        raise ValueError(f"client '{client_id}' not found.")
    
    # Defaults
    currency = currency or client.get("currency", "USD")
    vat_rate = float(vat_rate if vat_rate is not None else client.get("default_vat", 0.0))
    invoice_data = invoice_date or date.today()

    # Numbering
    existing_numbers = [inv.get("number", "") for inv in ws.invoices if inv.get("number")]
    next_suffix = _next_invoice_suffix(existing_numbers)
    number = _format_invoice_number(invoice_data, next_suffix)

    totals = _compute_totals(line_items, vat_rate)

    inv_id = f"inv_{invoice_data.year}_{next_suffix:03.d}"
    invoice = {
        "id": inv_id,
        "client_id": client_id,
        "number": number,
        "date": invoice_data.isoformat(),
        "due_days": int(due_days),
        "currency": currency,
        "vat_rate":vat_rate,
        "line_items": line_items,
        "status": "draft",
        **totals
    }

    if notes:
        invoice["notes"] = notes

    # Save session
    ws.invoices.append(invoice)

    # Summary for UI
    summary = (
        f"Draft invoice {number} for {client['name']}: "
        f"{format_money(invoice['subtotal'], Currency(currency))} + VAT "
        f"= {format_money(invoice['total'], Currency(currency))} (due in {due_days} days)"
    )

    return {"invoice": invoice, "summary": summary}
    
def chase_late_players(*, user_role: str, today: Optional[date] = None) -> Dict[str, Any]:
    """
    Find overdue invoices and return suggested reminder messages.
    """

    if not can(user_role, "send_reminder"):
        raise PermissionError("You do not have permission to send reminders.")
    
    ws = _require_ws()
    today = today or date.today()
    overdue = selectors.get_overdue_invoices(ws, today=today)

    reminders = []
    for inv in overdue:
        client = selectors.get_client_by_id(ws, inv["client_id"]) or {"name": "Unkown client"}
        due_by = date.fromisoformat(inv["date"]) + timedelta(days=int(inv.get("due_days", 14)))
        body = (
            f"Hi {client['name']},\n\n"
            f"This is a friendly reminder that invoice {inv['number']} "
            f"({format_money(inv['total'], Currency(inv['currency']))}) "
            f"was due on {due_by.isoformat()}.\n\n"
            f"Could you please arrange payment at your earliest convenience? "
            f"Let me know if you need us to resend the invoice.\n\n"
            f"Best regards,\nAccounts"
        )
        reminders.append({
                        "client_id": inv["client_id"],
            "client_name": client["name"],
            "invoice_number": inv["number"],
            "due_date": due_by.isoformat(),
            "amount": format_money(inv["total"], Currency(inv["currency"])),
            "message_subject": f"Overdue: {inv['number']} ({client['name']})",
            "message_body": body
        })
    
    return {
        "count_overdue": len(overdue),
        "reminders": reminders
    }