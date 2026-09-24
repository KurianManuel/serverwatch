"""Authentication provider abstraction."""

from abc import ABC, abstractmethod
from typing import Optional, Protocol, Mapping, Any
from app.auth.models import UserIdentity


class RequestLike(Protocol):
    """Protocol for request objects with headers."""
    @property
    def headers(self) -> Mapping[str, str]: ...


class AuthProvider(ABC):
    """Abstract authentication provider."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider name (e.g., 'tailscale', 'local', 'oidc')."""
        ...

    @abstractmethod
    async def authenticate(self, request: RequestLike) -> Optional[UserIdentity]:
        """Authenticate a request and return user identity."""
        ...

    async def authenticate_any(self, request: Any) -> Optional[UserIdentity]:
        """Wrapper to accept any request type."""
        return await self.authenticate(request)  # type: ignore[arg-type]


class ProviderRegistry:
    """Registry of authentication providers."""

    def __init__(self) -> None:
        self._providers: dict[str, AuthProvider] = {}

    def register(self, provider: AuthProvider) -> None:
        """Register a provider."""
        self._providers[provider.name] = provider

    def get(self, name: str) -> Optional[AuthProvider]:
        """Get a provider by name."""
        return self._providers.get(name)

    def all(self) -> list[AuthProvider]:
        """Get all registered providers."""
        return list(self._providers.values())


provider_registry = ProviderRegistry()