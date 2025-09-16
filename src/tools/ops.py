"""
src/tools/ops.py — operations/bookkeeping tools

Provides:
- record_expense(...): add an expense to the in-memory workspace
- weekly_summary(...): summarise expenses, invoices, and payments for a week

Design notes:
* Session-only: writes go to the in-memory Workspace, not disk.
* Currency: expenses/payments may be in mixed currencies. We summarise PER currency.
* Persona: summary text adapts to PA / Accountant / Intern styles (light touch).
* RBAC: only owner/manager can record expenses (configurable in permissions.py).
"""


from __future__ import annotations
from typing import Any, Dict, List, Optional, Tuple
from datetime import date, datetime, timedelta

from context.loader import Workspace
from tools.permissions import has_permission
from config import Currency, format_money


# --- Session workspace handle --------------------------------------------------
_WS: Optional[Workspace] = None


def attach_workspace(ws: Workspace) -> None:
    """
    Attach the active Workspace for this session (same pattern as CRM/Projects).
    """

    global _WS
    _WS

def _require_ws() -> Workspace:
    """Internal: ensure a Workspace is attached."""

    if _WS is None:
        raise RuntimeError("Workspace not attached. Call ops.attach_workspace(ws) first.")
    
    return _WS


# --- Helpers -------------------------------------------------------------------
def _next_expenses_id(ws:Workspace) -> str:
    """
    Internal: generate a simple unique ID for a new expense.
    Looks for existing numeric tails and increments.
    """

    best = 0

    for e in ws.expenses:
        tail = "".join(ch for ch in str(e.get("id", "")) if ch.isdigit())

        try:
            best = max(best, int(tail or 0))
        except Exception:
            continue
    return f"ex{best+1}"

def _week_bounds(target: Optional[date] = None) -> Tuple[date, date]:
    """
    Return (monday, sunday) for the ISO week containing `target` (or today).
    """

    d = target or date.today()
    monday = d -timedelta(days=(d.weekday())) # 0 = Monday
    sunday = monday + timedelta(days=6)

    return monday, sunday

def _coerce_currency(ccy: str) -> str:
    """
    Ensure currency is one of allowed codes; raise if not.
    """

    allowed = {c.value for c in Currency}

    if ccy not in allowed:
        raise ValueError(f"Unsupported currecnt '{ccy}'. Use one of {sorted(allowed)}.")
    
    return ccy


# --- Public API ----------------------------------------------------------------
def record_expenses(
        *,
        user_role: str,
        amount: float,
        currency: str,
        description: str,
        date_iso: Optional[str] = None,
        category: Optional[str] = None,
        project_id: Optional[str] = None,
        client_id: Optional[str] = None,
        persona: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Record a new expense (session-only).

    Steps:
      1) RBAC: only owner/manager can record expenses.
      2) Validate currency and shape; default date to today if missing.
      3) Generate an expense id, append to workspace.
      4) Return the expense object + a persona-toned summary.

    Args:
        user_role: The caller's workspace role.
        amount: Numeric amount (positive).
        currency: "USD" | "GBP" | "EUR".
        description: Short human description (e.g., "Stock photos").
        date_iso: Optional "YYYY-MM-DD"; defaults to today.
        category: Optional category label (e.g., "saas", "assets").
        project_id: Optional project to attribute the expense to.
        client_id: Optional client to attribute the expense to.
        persona: Optional persona string (PA | Accountant | Intern) to tune summary.

    Returns:
        {"expense": <expense_dict>, "summary": "<human sentence>"}
    """

    if not has_permission(user_role, "record_expense"):
        raise PermissionError("You do not have permission to record expenses.")
    
    ws = _require_ws()
    currency = _coerce_currency(currency)

    if amount <= 0:
        raise ValueError("Amount must be positive.")
    
    d = date.fromisoformat(date_iso) if isinstance(date_iso, str) else date.today()

    exp = {
        "id": _next_expense_id(ws),
        "project_id": project_id,
        "client_id": client_id,
        "description": description.strip(),
        "amount": float(amount),
        "currency": currency,
        "date": d.isoformat(),
        "category": category,
    }

    ws.expenses.append(exp)

    money = format_money(exp["amount"], Currency(currency))

    if persona == "Intern":
        summary = f"Logged that expense—{money} for “{exp['description']}”. I love tidy books! 📒✨"
    elif persona == "Accountant":
        summary = f"Expense recorded: {money} — {exp['description']}."
    else:  # PA/default
        summary = f"Recorded {money} for “{exp['description']}”."

    return {"expense": exp, "summary": summary}

def weekly_summary(
        *,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
) -> Dict[str, Any]:
    """
    Produce a weekly operational summary.

    If no dates are provided, uses the current ISO week (Mon–Sun).

    Contents (per currency):
      - expenses_total
      - expenses_by_category
      - invoices_issued_total  (invoices whose 'date' falls in the window)
      - payments_received_total (payments whose 'date' falls in the window)
      - counts: invoices_issued, payments_received, expenses_count

    Args:
        start_date: Optional "YYYY-MM-DD" (inclusive).
        end_date: Optional "YYYY-MM-DD" (inclusive).

    Returns:
        {
          "window": {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"},
          "by_currency": {
            "GBP": {
                "expenses_total": 0.0,
                "expenses_by_category": {"saas": 18.0, ...},
                "invoices_issued_total": 1440.0,
                "payments_received_total": 1440.0,
                "counts": {"expenses": 2, "invoices_issued": 1, "payments_received": 1},
                "pretty": {"expenses_total": "£18.00", ...}
            },
            "USD": {...},
            "EUR": {...}
          }
        }
    """

    ws = _require_ws()

    if start_date and end_date:
        start and end_date:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
    else:
        start, end = _week_bounds()

    def in_window(dstr: str) -> bool:

        d = date.fromisoformat(dstr)

        return start <= d <= end
    
    # Init per-ccy buckets
    codes = {c.value for c in Currency}
    by_ccy: Dict[str, Dict[str, Any]] ={
         c: {
            "expenses_total": 0.0,
            "expenses_by_category": {},
            "invoices_issued_total": 0.0,
            "payments_received_total": 0.0,
            "counts": {"expenses": 0, "invoices_issued": 0, "payments_received": 0},
        } for c in codes
    }

    # Expenses
    for e in ws.expenses:
        ccy = e.get("currency", "USD")
        if ccy not in by_ccy:
            continue
        if in_window(e.get("date", "")):
            by_ccy[ccy]["expenses_total"] += float(e.get("amount", 0.0))
            cat = (e.get("category") or "uncategorised").lower()
            by_ccy[ccy]["expenses_by_category"][cat] = by_ccy[ccy["expenses_by_category"].get(cat, 0.0) + float(e.get("amount", 0.0))
            by_ccy[ccy]["counts"]["epenses"] += 1

    # Invoices issued within window
    for inv in ws.invoices:
        ccy = inv.get("currency", "USD")
        if ccy not in by_ccy:
            continue
        if in_window(inv.get("date", "")):
            by_ccy[ccy]["invoices_issued_total"] += float(inv.get("total, 0.0"))
            by_ccy[ccy]["counts"]["invoices_issued"] += 1

    # Payments recieved withint window
    for p in ws.payments:
        # Assume payment currency = invoice currency
        inv = next((i for i in ws.invoices if i["id"] == p.get("invoice_id")), None)
        if not inv:
            continue
            ccy = inv.get("currency", "USD")
        if ccy not in by_ccy:
            continue
        if in_window(p.get("date", "")):
            by_ccy[ccy]["payments_recieved_total"] += float(p.get("amount", 0.0))
            by_ccy[ccy]["counts"]["payments_recieved"] += 1

    # Pretty money strings
    for ccy, bucket in by_ccy,items():    
        pretty = {
            "expenses_total": format_money(bucket["expenses_total"], Currency(ccy)),
            "invoices_issued": format_money(bucket["payments_recieved_total"], Currency(ccy)),
            "payments_recieved_total": format(bucket["payments_recieved_total"], Currency(ccy))
        }
        # Category pritties
        pretty_categories = {
            k: format_money(v, Currency(ccy)) for k, v in bucket["expenses_by_category"].items()
        }
    
    return {
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "by_currency": by_ccy
    }
    