"""Tailscale authentication provider."""



from app.auth.models import UserIdentity
from app.auth.provider import AuthProvider, RequestLike


class TailscaleProvider(AuthProvider):
    """Tailscale identity provider for MVP."""

    @property
    def name(self) -> str:
        return "tailscale"

    async def authenticate(self, request: RequestLike) -> UserIdentity | None:
        """
        Extract Tailscale identity from request headers.

        Tailscale Serve passes identity via headers when configured.
        Only trust headers when request comes through trusted proxy path.
        """
        # Header names from Tailscale Serve
        user_id = request.headers.get("X-Tailscale-User-Id")
        user_name = request.headers.get("X-Tailscale-User-Name")
        user_email = request.headers.get("X-Tailscale-User-Email")

        if not user_id:
            return None

        # MVP: All authenticated tailnet users are Viewers
        # Administrator role would be configured separately
        roles = {"Viewer"}

        return UserIdentity(
            id=user_id,
            provider="tailscale",
            subject=user_id,
            display_name=user_name,
            email=user_email,
            roles=roles,
        )
