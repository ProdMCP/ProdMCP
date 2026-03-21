"""Security layer for ProdMCP.

Provides security scheme definitions, token extraction, and validation.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from .exceptions import ProdMCPSecurityError

logger = logging.getLogger(__name__)


@dataclass
class SecurityContext:
    """Holds the security information extracted from a request."""

    user: dict[str, Any] | None = None
    token: str | None = None
    scopes: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class SecurityScheme(ABC):
    """Base class for security schemes."""

    scheme_type: str = "unknown"

    @abstractmethod
    def extract(self, context: dict[str, Any]) -> SecurityContext:
        """Extract security information from the request context.

        Args:
            context: A dict containing request metadata (headers, params, etc.)

        Returns:
            A SecurityContext with extracted credentials.

        Raises:
            ProdMCPSecurityError: If extraction fails.
        """

    @abstractmethod
    def to_spec(self) -> dict[str, Any]:
        """Return the OpenMCP/OpenAPI-style security scheme definition."""


class BearerAuth(SecurityScheme):
    """Bearer token authentication."""

    scheme_type = "http"

    def __init__(self, scopes: list[str] | None = None) -> None:
        self.scopes = scopes or []

    def extract(self, context: dict[str, Any]) -> SecurityContext:
        headers: dict[str, str] = context.get("headers", {})
        auth_header = headers.get("authorization", headers.get("Authorization", ""))
        if not auth_header.startswith("Bearer "):
            raise ProdMCPSecurityError(
                "Missing or invalid Bearer token", scheme="bearerAuth"
            )
        token = auth_header[7:]
        return SecurityContext(token=token, scopes=self.scopes)

    def to_spec(self) -> dict[str, Any]:
        return {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
        }


class ApiKeyAuth(SecurityScheme):
    """API key authentication via header or query parameter."""

    scheme_type = "apiKey"

    def __init__(
        self,
        key_name: str = "X-API-Key",
        location: str = "header",
    ) -> None:
        self.key_name = key_name
        self.location = location  # "header" or "query"

    def extract(self, context: dict[str, Any]) -> SecurityContext:
        if self.location == "header":
            headers: dict[str, str] = context.get("headers", {})
            api_key = headers.get(self.key_name, headers.get(self.key_name.lower(), ""))
        else:
            params: dict[str, str] = context.get("query_params", {})
            api_key = params.get(self.key_name, "")

        if not api_key:
            raise ProdMCPSecurityError(
                f"Missing API key in {self.location}: {self.key_name}",
                scheme="apiKey",
            )
        return SecurityContext(token=api_key, metadata={"key_name": self.key_name})

    def to_spec(self) -> dict[str, Any]:
        return {
            "type": "apiKey",
            "name": self.key_name,
            "in": self.location,
        }


class CustomAuth(SecurityScheme):
    """Custom authentication using a user-provided callable."""

    scheme_type = "custom"

    def __init__(
        self,
        extractor: Any,  # Callable[[dict], SecurityContext]
        spec: dict[str, Any] | None = None,
    ) -> None:
        self._extractor = extractor
        self._spec = spec or {"type": "custom"}

    def extract(self, context: dict[str, Any]) -> SecurityContext:
        try:
            return self._extractor(context)
        except Exception as exc:
            raise ProdMCPSecurityError(
                f"Custom auth failed: {exc}", scheme="custom"
            ) from exc

    def to_spec(self) -> dict[str, Any]:
        return self._spec


class SecurityManager:
    """Manages security validation for handlers."""

    # Registry of named security scheme instances
    _schemes: dict[str, SecurityScheme]

    def __init__(self) -> None:
        self._schemes = {}

    def register_scheme(self, name: str, scheme: SecurityScheme) -> None:
        """Register a named security scheme."""
        self._schemes[name] = scheme

    def get_scheme(self, name: str) -> SecurityScheme | None:
        return self._schemes.get(name)

    def check(
        self,
        context: dict[str, Any],
        security_config: list[dict[str, Any]],
    ) -> SecurityContext:
        """Validate the request against security requirements.

        Security requirements follow OpenAPI-style: a list of dicts where
        each dict maps a scheme name to its required scopes. The request
        must satisfy at least one requirement (logical OR).

        Args:
            context: Request context dict.
            security_config: List of security requirement objects.

        Returns:
            A SecurityContext on success.

        Raises:
            ProdMCPSecurityError: If no requirement is satisfied.
        """
        if not security_config:
            return SecurityContext()

        last_error: ProdMCPSecurityError | None = None
        for requirement in security_config:
            try:
                return self._check_requirement(context, requirement)
            except ProdMCPSecurityError as exc:
                last_error = exc
                continue

        raise last_error or ProdMCPSecurityError("Authentication required")

    def _check_requirement(
        self,
        context: dict[str, Any],
        requirement: dict[str, Any],
    ) -> SecurityContext:
        """Check a single security requirement."""
        # Support shorthand: {"type": "bearer", "scopes": [...]}
        if "type" in requirement:
            return self._check_shorthand(context, requirement)

        # OpenAPI-style: {"bearerAuth": ["scope1"]}
        for scheme_name, scopes in requirement.items():
            scheme = self._schemes.get(scheme_name)
            if scheme is None:
                raise ProdMCPSecurityError(
                    f"Unknown security scheme: {scheme_name}",
                    scheme=scheme_name,
                )
            sec_ctx = scheme.extract(context)
            if scopes and not all(s in sec_ctx.scopes for s in scopes):
                raise ProdMCPSecurityError(
                    f"Insufficient scopes for {scheme_name}",
                    scheme=scheme_name,
                )
            return sec_ctx

        return SecurityContext()

    def _check_shorthand(
        self,
        context: dict[str, Any],
        requirement: dict[str, Any],
    ) -> SecurityContext:
        """Handle shorthand security config like {"type": "bearer", "scopes": [...]}."""
        auth_type = requirement.get("type", "").lower()
        scopes = requirement.get("scopes", [])

        if auth_type == "bearer":
            scheme = BearerAuth(scopes=scopes)
            return scheme.extract(context)
        elif auth_type == "apikey":
            key_name = requirement.get("key_name", "X-API-Key")
            location = requirement.get("in", "header")
            scheme = ApiKeyAuth(key_name=key_name, location=location)
            return scheme.extract(context)
        else:
            raise ProdMCPSecurityError(
                f"Unknown auth type: {auth_type}", scheme=auth_type
            )

    def generate_schemes_spec(self) -> dict[str, Any]:
        """Generate the securitySchemes component for OpenMCP spec."""
        return {name: scheme.to_spec() for name, scheme in self._schemes.items()}

    def generate_security_spec(
        self, security_config: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Generate the security field for an entity in OpenMCP spec.

        Normalizes shorthand configs into OpenAPI-style references.
        """
        result: list[dict[str, Any]] = []
        for requirement in security_config:
            if "type" in requirement:
                auth_type = requirement.get("type", "").lower()
                scopes = requirement.get("scopes", [])
                if auth_type == "bearer":
                    scheme_name = "bearerAuth"
                    if scheme_name not in self._schemes:
                        self.register_scheme(scheme_name, BearerAuth(scopes=scopes))
                    result.append({scheme_name: scopes})
                elif auth_type == "apikey":
                    scheme_name = "apiKeyAuth"
                    if scheme_name not in self._schemes:
                        key_name = requirement.get("key_name", "X-API-Key")
                        location = requirement.get("in", "header")
                        self.register_scheme(
                            scheme_name, ApiKeyAuth(key_name=key_name, location=location)
                        )
                    result.append({scheme_name: scopes})
                else:
                    result.append(requirement)
            else:
                result.append(requirement)
        return result
