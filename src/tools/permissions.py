"""
src/tools/permissions.py — minimal role-based access control (RBAC)

RBAC = Role-Based Access Control. Instead of granting permissions to specific
people, we grant them to roles (e.g., "manager"). Anyone with that role can do
the action. This keeps rules simple and scalable.

Usage:
    from tools.permissions import has_permission
    if not has_permission(user_role, "create_invoice"):
        raise PermissionError("You do not have permission.")
"""


from typing import Literal


Role = Literal["owner", "manager", "member", "viewer"]

# Minimal default
ACTION_MATRIX = {
    "create_invoice": {"owner", "manager"},
    "send_reminder": {"owner", "manager"},
    "record_payment": {"owner", "manager"},
    "record_expense": {"owner", "manager"},
    "create_task": {"owner", "manager", "member"},
    "move_task": {"owner", "manager", "member"},
}


def has_permission(user_role: Role, action: str) -> bool:
    """
    Return True if the given role is allowed to perform `action`.

    Args:
        user_role: One of "owner" | "manager" | "member" | "viewer".
        action: The action string to check, e.g., "create_invoice".

    Why this name?
        `has_permission(...)` is explicit and readable in code. You may see
        `can(...)` used in some codebases; this project uses the clearer name.
    """

    allowed = ACTION_MATRIX.get(action, set())

    return user_role in allowed