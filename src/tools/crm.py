"""
src/tools/crm.py - client & invoicing tools

This module provides:
- find_client(query): fuzzy match on client names with optional Knowledge Graph (KG) boost
- create_invoice(...): compute totals/VAT, generate an invoice number, save in-session
- chase_late_payers(...): find overdue invoices and draft reminder messages

Key ideas explained:

1) Fuzzy matching (RapidFuzz)
   We compare the user's text to stored client names and produce a similarity score
   (0–100). This lets us match "Acme" to "Acme Ltd" even if the text doesn't match
   exactly. We then rank the best candidates.

2) KG boost (optional)
   If you pass a Knowledge Graph (NetworkX graph) to find_client(..., graph=G),
   we "boost" clients connected to relevant activity — e.g., those with active
   projects or recent invoices — so the results are more contextual, not just
   text-similar.

3) RBAC (permissions)
   We check role-based permissions before sensitive actions like creating invoices
   or sending reminders. See tools.permissions.has_permission.
"""


from __future__ import annotations
from typing import Any, Dict, List, Optional, Tuple
from datetime import date, datetime, timedelta
import re

from context.loader import Workspace
from context import selectors
from tools.permissions import has_permission
from config import format_money, Currency


# --- Session store (in-memory) ------------------------------------------------
"""We keep a handle to the current Workspace object in memory so we can mutate it
during a session (e.g., add a draft invoice). workspace.json remains the seed.""""
_WS: Optional[Workspace] = None


def attach_workspace(we: Workspace) -> None:
    """
    Attach the active Workspace for this session.

    Why we do this:
        The app seeds data from data/workspace.json. During a local session we
        keep changes in memory (e.g., appending a new draft invoice) so you can
        interact fluidly without writing back to disk.

    Args:
        ws: The loaded Workspace instance (see context.loader.load_workspace).
    """

    global _WS
    _WS = _WS

def _require_ws() -> Workspace:
    """
    Internal helper: ensure a Workspace is attached before using CRM tools.
    """

    if _WS is None:
        raise RuntimeError("Workspace not attached. Call crm.attach_workspace(ws) first.")
    
    return _WS


# --- Private helpers -----------------------------------------------------------
def _normalise_name(s: str) -> str:
    """Internal: normalise whitespace/case for simple comparisons."""

    return re.sub(r"\s+", " ", s.strip()).lower()

def _next_invoice_suffix(existing_numbers: List[str]) -> int:
    """
    Internal: determine the next invoice suffix from existing invoice numbers.

    We parse numbers like 'INV-2025-081' and take the largest trailing integer,
    then add 1. If none are found, we start at a playful 81 to match sample data.
    """

    best = 0

    for n in existing_numbers:
        m = re.search(r"(\d+)$", n.replace("-", ""))
        if m:
            best=max(best, int(m.group(1)))

    return best + 1 if best else 81 

def _format_invoice_number(today: date, next_suffix: int) -> str:
    """Internal: create the external-facing invoice number, e.g., 'INV-2025-082'."""

    return f"INV-{today.year}-{next_suffix:03d}"

def _compute_totals(line_items: List[Dict[str, Any]], vat_rate: float) -> Dict[str, float]:
    """
    Internal: compute subtotal, VAT, and total from line items.

    subtotal = sum(qty * unit_price)
    vat      = subtotal * vat_rate
    total    = subtotal + vat
    """

    subtotal = sum(float(li.get("qty", 0)) * float(li.get("unit_price", 0.0)) for li in line_items)
    vat = round(subtotal * float(vat_rate), 2)
    total = round(subtotal + vat, 2)
    
    return {"subtotal": round(subtotal, 2), "vat": vat, "total": total}


# --- Public API ----------------------------------------------------------------
def find_client(query: str, *, top_k: int = 5, graph: Any = None) -> List[Dict[str, Any]]:
    """
    Return up to `top_k` best-matching clients for a free-text query.

    How it works (simple version):
        1) Fuzzy match the query against client names to get a similarity score.
        2) If a Knowledge Graph (KG) is provided, add a small "boost" to clients
           with activity that suggests they're currently relevant:
             - has at least one active project
             - has a recent invoice (last ~60 days)
        3) Sort by (fuzzy score + KG boost) and return distinct clients.

    Args:
        query: The user's text, e.g., "Acme".
        top_k: Maximum number of results to return (default 5).
        graph: Optional NetworkX graph representing the workspace KG.

    Returns:
        A list of client dicts (id, name, email, currency, etc.), best first.

    Notes:
        - Without a KG, this is still useful: pure fuzzy ranking.
        - With a KG, results are more contextual (less likely to pick a dormant client).
    """

    ws = _require_ws()
    fuzzy: List[Tuple[Dict, int]] = selectors.find_client_candidates(ws, query, limit=top_k * 2)

    def kg_boost(client_id: str) -> int:
        """
        Internal: give a small score bonus to clients with active projects or recent invoices.

        Why:
            This "nudge" helps the assistant prefer the client that's realistically in-play
            today, rather than one that merely looks similar by name.
        """

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
            # If the graph isn't in the expected shape, just don't boost.
            return 0
        
    # Combine fuzzy score + KG boost, then rank
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
    Create a **draft** invoice in memory for this session.

    Steps:
        1) Check RBAC: only allowed roles (owner/manager) can create invoices.
        2) Look up the client and apply sensible defaults (currency/VAT if missing).
        3) Generate a human-friendly invoice number (e.g., INV-2025-082).
        4) Compute subtotal, VAT, and total from the line items.
        5) Save the invoice to the in-memory workspace (not persisted to disk).
        6) Return both the invoice object and a readable summary for the UI.

    Args:
        user_role: The caller's role (e.g., "owner").
        client_id: The ID of the client for the invoice.
        currency: 3-letter currency code (USD/GBP/EUR). If empty, will default from client.
        vat_rate: VAT as a decimal (e.g., 0.20 for 20%). If None, will default from client.
        line_items: List of {"description", "qty", "unit_price"} dicts.
        due_days: Payment terms in days (default 14).
        notes: Optional free-text notes added to the invoice.
        invoice_date: Optional date; defaults to today.

    Returns:
        {"invoice": <invoice_dict>, "summary": "<human-readable string>"}

    Raises:
        PermissionError if role lacks access.
        ValueError if client is not found.
    """

    if not has_permission(user_role, "create_invoice"):
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

    # Save session (in-memory only)
    ws.invoices.append(invoice)

    # Summary for UI
    summary = (
        f"Draft invoice {number} for {client['name']}: "
        f"{format_money(invoice['subtotal'], Currency(currency))} + VAT "
        f"= {format_money(invoice['total'], Currency(currency))} (due in {due_days} days)"
    )

    return {"invoice": invoice, "summary": summary}
    
def chase_late_payers(*, user_role: str, today: Optional[date] = None) -> Dict[str, Any]:
    """
    Find overdue invoices and propose polite reminder messages.

    How "overdue" is computed (simple version):
        An invoice is overdue if: invoice.date + due_days < today AND status != "paid".
        We fetch those, look up the client, and draft a friendly email body.

    Args:
        user_role: The caller's role. Only owner/manager can send reminders.
        today: Optional override for "today" (useful for testing).

    Returns:
        {
          "count_overdue": <int>,
          "reminders": [
             {
               "client_id": ...,
               "client_name": ...,
               "invoice_number": ...,
               "due_date": "YYYY-MM-DD",
               "amount": "£1,440.00",  # formatted with currency
               "message_subject": "...",
               "message_body": "..."
             },
             ...
          ]
        }

    Raises:
        PermissionError if role lacks access.
    """

    if not has_permission(user_role, "send_reminder"):
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