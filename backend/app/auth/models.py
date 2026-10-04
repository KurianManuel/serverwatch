"""Authentication models."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class UserIdentity:
    """Internal user identity abstraction."""

    id: str
    provider: str
    subject: str
    display_name: str | None = None
    email: str | None = None
    roles: set[str] = field(default_factory=set)

    def has_role(self, role: str) -> bool:
        """Check if user has a specific role."""
        return role in self.roles

    def is_administrator(self) -> bool:
        """Check if user is an administrator."""
        return self.has_role("Administrator")

    def is_viewer(self) -> bool:
        """Check if user is a viewer."""
        return self.has_role("Viewer")
