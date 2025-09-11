"""
src/app.py
"""


import json
import gradio as gr
from datetime import datetime
from config import Persona, Currency, DEFAULT_PERSONA, DEFAULT_CURRENCY, DEFAULT_VAT, DEFAULT_TERM_DAYS


APP_TITLE = "Business-Assistant (Local Demo)"
APP_DESC = (
    "Type short commands like: "
    "'create invoice for Acme for August retainer' or 'move Hire designer to Doing'. "
    "This starter app wires up tabs, persona & currency toggles. "
)


def handel_command(command: str, persona: str, currency: str, tab: str):
    """
    Temporary stub: echoes the command with current settings and a fake audit log.
    This will be replaced by the orchestrator (OpenAI function calling + tools).
    """

    persona_note = {
        Persona.PA.value: "Friendly & professional.",
        Persona.ACCOUNTANT.value: "Terse & number-perfect.",
        Persona.INTERN.value: "Over-eager admin goblin (still useful!).",
    }.get(persona, "Friendly & professional.")

    # Demo auto-completion defaults
    vat = DEFAULT_VAT.get(currency, 0.0)
    terms = DEFAULT_TERM_DAYS

    result = {
        "tab": tab,
        "persona": persona,
        "currency": currency,
        "assumed_defaults": {"vat_rate": vat, "payment_terms_days": terms},
        "input_command": command.strip(),
        "output_summary": (
            "Stub response — orchestrator not connected yet. "
            "Next step is routing to tools based on intent."
        ),
        "audit_log": [
            {
                "ts": datetime.utcnow().isoformat() + "Z",
                "step": "parse_intent",
                "ok": True,
                "detail": "Parsed high-level intent from command (stub).",
            },
            {
                "ts": datetime.utcnow().isoformat() + "Z",
                "step": "select_tools",
                "ok": True,
                "detail": f"Would select tools for tab='{tab}' (stub).",
            },
            {
                "ts": datetime.utcnow().isoformat() + "Z",
                "step": "apply_defaults",
                "ok": True,
                "detail": f"Applied defaults: VAT={vat*100:.0f}%, Terms={terms} days.",
            },
        ],
    }
    result_json = json.dumps(result, indent=2)

    return result_json

def build_tab(label: str):
    """
    Create a simple tab layout with:
    - command textbox
    - run button
    - JSON output (stub)
    """

    with gr.Tab(label):
        gr.Markdown(f"### {label}")
        cmd = gr.Textbox(
            label="Command",
            placeholder="e.g., create invoice for Acme for August retainer",
            lines=2
        )
        out = gr.Code(label="Result (JSON stub)", language="json")
        run = gr.Button("Run", variant="primary")

    return {"cmd": cmd, "out": out, "run": run}

def app():
    with gr.Blocks(title=APP_TITLE) as demo:
        gr.Markdown(f"# {APP_TITLE}")
        gr.Markdown(APP_DESC)

        with gr.Row():
            persona_dd = gr.Dropdown(
                label="Persona",
                choices=[p.value for p in Persona],
                value=DEFAULT_PERSONA.value,
                info="PA (friendly), Acccountant (terse), Intern (eager)."
            )
            currency_dd = gr.Dropdown(
                label="Currency",
                choices=[c.value for c in Currency],
                value=DEFAULT_CURRENCY.value,
                info="USD default; also supports GBP and EUR."
            )
        
        # Tabs
        crm = build_tab("CRM")
        projects = build_tab("Projects")
        ops = build_tab("Ops")

        # Wire buttons
        crm["run"].click(
            fn=lambda command, persona, currency: handel_command(
                command, persona, currency, "CRM"
            ),
            inputs=[crm["cmd"], persona_dd, currency_dd,],
            outputs=[crm["out"]]
        )
        projects["run"].click(
            fn=lambda command, persona, currency: handel_command(
                command, persona, currency, "Projects"
            ),
            inputs=[projects["cmd"], persona_dd, currency_dd],
            outputs=[projects["out"]]
        )
        ops["run"].click(
            fn=lambda command, persona, currency: handel_command(
                command, persona, currency, "Ops"
            ),
            inputs=[ops["cmd"], persona_dd, currency_dd],
            outputs=[ops["out"]]
        )

    return demo


if __name__ == "__main__":

    app().launch()

# EOF