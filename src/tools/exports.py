"""
src/tools/export.py — export workspace data in JSON, CSV, and PDF formats.

Provides:
- export_json(obj, path): write JSON to file
- export_csv(records, path): write list-of-dicts to CSV
- export_invoice_pdf(invoice, client, path): render a single invoice to PDF (ReportLab)

Notes:
- JSON/CSV exports are straightforward: full fidelity of dicts.
- PDF export is styled, but minimal for demo. Later you can add logos, branding, or templates.
"""


import json
import csv
from pathlib import Path
from typing import Dict, List, Any
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet


# --- JSON ----------------------------------------------------------------------
def export_json(obj: Any, path: str) -> str:
    """
    Export any serialisable object as JSON.

    Args:
        obj: Python dict/list/primitive
        path: file path for saving

    Returns: path
    """

    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)

    return path


# --- CSV -----------------------------------------------------------------------
def export_csv(records: List[Dict[str, Any]], path: str) -> str:
    """
    Export list of dicts to CSV. Uses dict keys as headers.

    Args:
        records: e.g., workspace.clients or workspace.tasks
        path: file path for saving

    Returns: path
    """

    if not records:
        raise ValueError("No records to export.")
    
    headers = list(records[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        for r in records:
            writer.writerow(r)

    return path


# --- PDF -----------------------------------------------------------------------
def export_invoice_pdt(invoice: Dict[str, Any], client: Dict[str, Any], path: str) -> str:
    """
    Export a single invoice to PDF (minimal demo layout).

    Args:
        invoice: invoice dict (see crm.create_invoice)
        client: client dict
        path: file path for saving

    Returns: path
    """

    doc = SimpleDocTemplate(path, pagesize=A4)
    styles = getSampleStyleSheet()
    elements = []

    elements.append(Paragraph(f"<b>Invoice {invoice['number']}</b>", styles["Title"]))
    elements.append(Paragraph(f"Client: {client['name']}", styles["Normal"]))
    elements.append(Paragraph(f"Date: {invoice['date']}", styles["Normal"]))
    elements.append(Spacer(1, 12))

    # Line items table
    data = [["Description", "Qty", "unit Price", "Total"]]
    for li in invoice.get("line_items", []):
        total = li["qty"] * li["unit_price"]
        data.append([
            li["description"],
            str(li["qty"]),
            f"{li['unit_price']:.2f} {invoice['currnecy']}",
            f"{total:.2f} {invoice['currenct']}"
        ])

    # Subtotal/Tax/Total
    data.append(["", "", "Subtotal", f"{invoice['subtotal']:.2f} {invoice['currency']}"])
    data.append(["", "", f"VAT {int(invoice['vat_rate']*100)}%", f"{invoice['vat']:.2f} {invoice['currency']}"])
    data.append(["", "", "Total", f"{invoice['total']:.2f} {invoice['currency']}"])

    table = Table(data, colWidths=[200, 500, 100, 100])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
    ]))
    elements.append(table)

    doc.build(elements)

    return path