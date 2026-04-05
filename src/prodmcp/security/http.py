"""HTTP security schemes for ProdMCP."""

from __future__ import annotations

import base64
import logging
from typing import Any

from ..exceptions import ProdMCPSecurityError
from .base import SecurityContext, SecurityScheme

logger = logging.getLogger(__name__)


class HTTPBearer(SecurityScheme):
    """Bearer token authentication.

    Args:
        scopes: Required scopes for this scheme (declared, not enforced without
            ``scope_validator``).
        scope_validator: Optional callable ``(token: str) -> list[str]`` that
            inspects the raw token (e.g. decodes a JWT) and returns the scopes
            actually granted by it.  **Without this, scope enforcement is
            disabled** — only token presence is checked.  A ``UserWarning`` is
            emitted at request time when scopes are declared but no validator
            is provided.
    """

    scheme_type = "http"

    def __init__(
        self,
        scopes: list[str] | None = None,
        scope_validator: Any | None = None,
    ) -> None:
        self.scopes = scopes or []
        # callable(token: str) -> list[str] of actually-granted scopes
        self.scope_validator = scope_validator
        # Bug P3-3 fix: emit the warning once at construction time, not once
        # per request inside extract() — which would spam logs on every call.
        if self.scopes and scope_validator is None:
            import warnings
            warnings.warn(
                f"HTTPBearer has required scopes {self.scopes!r} but no "
                "scope_validator is configured — scope enforcement is DISABLED. "
                "Provide a scope_validator callable (e.g. a JWT decoder) to "
                "verify that the token actually grants these scopes.",
                UserWarning,
                stacklevel=2,
            )

    def extract(self, context: dict[str, Any]) -> SecurityContext:
        headers: dict[str, str] = context.get("headers", {})
        auth_header = headers.get("authorization", headers.get("Authorization", ""))
        
        if not auth_header.startswith("Bearer "):
            raise ProdMCPSecurityError(
                "Missing or invalid Bearer token", scheme="bearerAuth"
            )
        
        # B9 fix: use len(prefix) instead of hardcoded 7 — change-safe.
        token = auth_header[len("Bearer "):]

        if self.scope_validator is not None:
            actual_scopes = self.scope_validator(token)
        elif self.scopes:
            # Warning already emitted in __init__; no per-request noise.
            actual_scopes = list(self.scopes)
        else:
            actual_scopes = []

        return SecurityContext(token=token, scopes=actual_scopes)

    def to_spec(self) -> dict[str, Any]:
        return {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
        }


class HTTPBasicAuth(SecurityScheme):
    """Basic HTTP authentication."""

    scheme_type = "http"

    def extract(self, context: dict[str, Any]) -> SecurityContext:
        headers: dict[str, str] = context.get("headers", {})
        auth_header = headers.get("authorization", headers.get("Authorization", ""))

        if not auth_header.startswith("Basic "):
            raise ProdMCPSecurityError(
                "Missing or invalid Basic HTTP header", scheme="basicAuth"
            )

        try:
            _, encoded = auth_header.split(" ", 1)
            decoded = base64.b64decode(encoded).decode("utf-8")
            username, password = decoded.split(":", 1)
        except Exception as e:
            raise ProdMCPSecurityError(
                "Invalid Basic authentication credentials", scheme="basicAuth"
            ) from e

        # N1 fix: do NOT store the plaintext password in metadata.
        # If SecurityContext is ever logged (e.g. by LoggingMiddleware), the
        # password would be leaked into log files.
        return SecurityContext(
            token=password,
            metadata={"username": username},
        )

    def to_spec(self) -> dict[str, Any]:
        return {
            "type": "http",
            "scheme": "basic",
        }


class HTTPDigestAuth(SecurityScheme):
    """Digest HTTP authentication."""

    scheme_type = "http"

    def extract(self, context: dict[str, Any]) -> SecurityContext:
        headers: dict[str, str] = context.get("headers", {})
        auth_header = headers.get("authorization", headers.get("Authorization", ""))

        if not auth_header.startswith("Digest "):
            raise ProdMCPSecurityError(
                "Missing or invalid Digest HTTP header", scheme="digestAuth"
            )

        # B9 fix: use len(prefix) instead of hardcoded 7 — change-safe.
        token = auth_header[len("Digest "):]
        return SecurityContext(token=token)

    def to_spec(self) -> dict[str, Any]:
        return {
            "type": "http",
            "scheme": "digest",
        }
