"""
src/config.py
"""


from enum import Enum
from typing import Dict


class Persona(str, Enum):

    PA = "PA"
    ACCOUNTANT = "Accountant"
    INTERN = "Intern"

class Currency(str, Enum):

    USD = "USD"
    GBP = "GBP"
    EUR = "EUR"


# Defaults
DEFAULT_PERSONA: Persona = Persona.PA
DEFAULT_CURRENCY: Currency = Currency.USD
DEFAULT_TERM_DAYS: int = 14                 # Payment term
DEFAULT_VAT: Dict[str, float] = {           # VAT by currency
    "USD": 0.00,
    "GBP": 0.20,
    "EUR": 0.20
}
CURRENCY_SYMBOLS: Dict[str, str] = {
    "USD": "$",
    "GBP": "£",
    "EUR": "€"
}


def format_money(amount:float, currency: Currency) -> str:
    """Very simple currency formatter"""

    sym = CURRENCY_SYMBOLS[str(currency)]

    return f"{sym}{amount:,.2f}"
# EOF