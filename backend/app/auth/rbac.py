"""Role-based access control."""

from enum import Enum
from typing import Set


class Role(str, Enum):
    """Application roles."""

    VIEWER = "Viewer"
    ADMINISTRATOR = "Administrator"


class Permission(str, Enum):
    """Application permissions."""

    READ_DASHBOARD = "read:dashboard"
    READ_METRICS = "read:metrics"
    READ_HISTORY = "read:history"
    READ_PROCESSES = "read:processes"
    READ_SERVICES = "read:services"
    READ_EVENTS = "read:events"
    READ_ALERTS = "read:alerts"
    READ_SYSTEM = "read:system"
    MANAGE_CONFIG = "manage:config"
    MANAGE_USERS = "manage:users"


ROLE_PERMISSIONS: dict[Role, Set[Permission]] = {
    Role.VIEWER: {
        Permission.READ_DASHBOARD,
        Permission.READ_METRICS,
        Permission.READ_HISTORY,
        Permission.READ_PROCESSES,
        Permission.READ_SERVICES,
        Permission.READ_EVENTS,
        Permission.READ_ALERTS,
        Permission.READ_SYSTEM,
    },
    Role.ADMINISTRATOR: {
        Permission.READ_DASHBOARD,
        Permission.READ_METRICS,
        Permission.READ_HISTORY,
        Permission.READ_PROCESSES,
        Permission.READ_SERVICES,
        Permission.READ_EVENTS,
        Permission.READ_ALERTS,
        Permission.READ_SYSTEM,
        Permission.MANAGE_CONFIG,
        Permission.MANAGE_USERS,
    },
}


def get_permissions_for_roles(roles: Set[str]) -> Set[Permission]:
    permissions: Set[Permission] = set()
    for role_str in roles:
        try:
            role = Role(role_str)
            permissions.update(ROLE_PERMISSIONS.get(role, set()))
        except ValueError:
            continue
    return permissions


def has_permission(roles: Set[str], permission: Permission) -> bool:
    permissions = get_permissions_for_roles(roles)
    return permission in permissions