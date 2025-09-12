"""
src/tools/permissions.py
"""


from typing import Literal


Role = Literal["owner", "manager", "member", "viewer"]

# Minimal default
ACTION_MATRIX = {
    "create_invoice": {"owner", "manager"},
    "send_reminder": {"owner", "manager"},
    "record_payment": {"owner", "manager"},
    "create_task": {"owner", "manager", "member"},
    "move_task": {"owner", "manager", "member"},
}


def can(user_role: Role, action: str) -> bool:

    allowed = ACTION_MATRIX.get(action, set())

    return user_role in allowed