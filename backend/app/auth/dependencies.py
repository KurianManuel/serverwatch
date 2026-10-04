"""Authentication and authorization dependencies."""

from collections.abc import Awaitable, Callable

from fastapi import Depends, HTTPException, Request, status

from app.auth.models import UserIdentity
from app.auth.provider import provider_registry
from app.auth.rbac import Permission, has_permission


async def get_current_user(request: Request) -> UserIdentity | None:
    """Get current authenticated user from request."""
    for provider in provider_registry.all():
        user = await provider.authenticate_any(request)
        if user:
            return user
    return None


async def require_authentication(
    user: UserIdentity | None = Depends(get_current_user),  # noqa: B008
) -> UserIdentity:
    """Require authenticated user."""
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    return user


def require_permission(permission: Permission) -> Callable[..., Awaitable[UserIdentity]]:
    """Create a dependency that requires a specific permission."""

    async def permission_checker(
        user: UserIdentity = Depends(require_authentication),  # noqa: B008
    ) -> UserIdentity:
        if not has_permission(user.roles, permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission denied: {permission.value}",
            )
        return user

    return permission_checker


def require_role(*roles: str) -> Callable[..., Awaitable[UserIdentity]]:
    """Create a dependency that requires one of the specified roles."""

    async def role_checker(
        user: UserIdentity = Depends(require_authentication),  # noqa: B008
    ) -> UserIdentity:
        if not any(user.has_role(role) for role in roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role required: {', '.join(roles)}",
            )
        return user

    return role_checker
