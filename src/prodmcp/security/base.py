"""Base security definitions for ProdMCP."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from ..exceptions import ProdMCPSecurityError

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
            context: A dict containing request metadata (headers, query_params, cookies, etc.)

        Returns:
            A SecurityContext with extracted credentials.

        Raises:
            ProdMCPSecurityError: If extraction fails.
        """

    @abstractmethod
    def to_spec(self) -> dict[str, Any]:
        """Return the OpenMCP/OpenAPI-style security scheme definition."""

    def __call__(self, context: dict[str, Any]) -> str | None:
        """Allow the scheme to be used directly as a dependency.
        
        Returns the extracted token.
        """
        sec_ctx = self.extract(context)
        return sec_ctx.token


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
        except ProdMCPSecurityError:
            raise  # auth errors propagate as-is
        except Exception as exc:
            # P3-N4 fix: non-auth exceptions from user extractor code (e.g.
            # TypeError, AttributeError) were previously buried under a generic
            # "Custom auth failed" message.  Surface the real exception type.
            raise ProdMCPSecurityError(
                f"Custom auth extractor raised {type(exc).__name__}: {exc}",
                scheme="custom",
            ) from exc

    def to_spec(self) -> dict[str, Any]:
        return self._spec


class SecurityManager:
    """Manages security validation for handlers."""

    # Registry of named security scheme instances
    _schemes: dict[str, SecurityScheme]

    def __init__(self) -> None:
        self._schemes = {}
        # C9 fix: initialize here instead of lazily via hasattr() in _check_shorthand.
        # Lazy init caused mypy "Attribute not defined" errors and potential
        # TOCTOU races in concurrent environments.
        self._shorthand_cache: dict[tuple, Any] = {}

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
        """Check a single security requirement.

        OpenAPI semantics: a requirement dict with multiple keys means ALL
        schemes must pass (logical AND).  This method checks every entry
        and raises on the first failure.
        """
        # Support shorthand: {"type": "bearer", "scopes": [...]}
        if "type" in requirement:
            return self._check_shorthand(context, requirement)

        # OpenAPI-style: {"bearerAuth": ["scope1"], "apiKeyAuth": []}
        # Bug E fix: ALL schemes in the dict must pass (AND semantics).
        # The previous implementation returned after the very first key,
        # silently skipping any remaining schemes.
        # B5 fix: merge all SecurityContexts instead of keeping only the last one.
        # With AND semantics (multiple required schemes), each scheme produces its
        # own SecurityContext. The old `last_ctx = sec_ctx` loop discarded every
        # scheme's token/scopes except the final one.  Now we:
        #   • keep the first non-None token as the "primary" token
        #   • union all scopes (order-preserving, deduplicated)
        #   • store each per-scheme context in merged_ctx.metadata[scheme_name]
        merged_ctx = SecurityContext()
        for scheme_name, scopes in requirement.items():
            scheme = self._schemes.get(scheme_name)
            if scheme is None:
                raise ProdMCPSecurityError(
                    f"Unknown security scheme: {scheme_name}",
                    scheme=scheme_name,
                )
            ctx = scheme.extract(context)
            if scopes and not all(s in ctx.scopes for s in scopes):
                raise ProdMCPSecurityError(
                    f"Insufficient scopes for {scheme_name}",
                    scheme=scheme_name,
                )
            # Merge: first token wins as primary; union scopes; capture per-scheme ctx
            if merged_ctx.token is None:
                merged_ctx.token = ctx.token
            # Deduplicated, order-preserving scope union
            merged_ctx.scopes = list(
                dict.fromkeys(merged_ctx.scopes + ctx.scopes)
            )
            merged_ctx.metadata[scheme_name] = ctx

        return merged_ctx

    def _check_shorthand(
        self,
        context: dict[str, Any],
        requirement: dict[str, Any],
    ) -> SecurityContext:
        """Handle shorthand security config like {"type": "bearer", "scopes": [...]}.

        N4 fix: scheme instances are cached on the SecurityManager to avoid
        creating a new object on every single request call.
        """
        auth_type = requirement.get("type", "").lower()
        scopes = requirement.get("scopes", [])

        # Build a stable cache key from the requirement's shape
        key_name = requirement.get("key_name", "X-API-Key")
        location = requirement.get("in", "header")
        cache_key = (auth_type, tuple(scopes), key_name, location)

        # C9 fix: _shorthand_cache is now initialized in __init__; no hasattr guard needed.
        if cache_key not in self._shorthand_cache:
            if auth_type == "bearer":
                from .http import HTTPBearer
                self._shorthand_cache[cache_key] = HTTPBearer(scopes=scopes)
            elif auth_type == "apikey":
                from .api_key import APIKeyHeader, APIKeyQuery, APIKeyCookie
                if location == "header":
                    self._shorthand_cache[cache_key] = APIKeyHeader(name=key_name)
                elif location == "query":
                    self._shorthand_cache[cache_key] = APIKeyQuery(name=key_name)
                elif location == "cookie":
                    self._shorthand_cache[cache_key] = APIKeyCookie(name=key_name)
                else:
                    raise ProdMCPSecurityError(f"Invalid api key location {location}", scheme="apikey")
            else:
                raise ProdMCPSecurityError(
                    f"Unknown auth type: {auth_type}", scheme=auth_type
                )

        scheme = self._shorthand_cache[cache_key]
        return scheme.extract(context)

    def generate_schemes_spec(self) -> dict[str, Any]:
        """Generate the securitySchemes component for OpenMCP spec."""
        return {name: scheme.to_spec() for name, scheme in self._schemes.items()}

    def generate_security_spec(
        self, security_config: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Generate the security field for an entity in OpenMCP spec.

        Normalizes shorthand configs into OpenAPI-style ``{schemeName: scopes}``
        references.  This method is **read-only** — it does NOT register any
        schemes into ``_schemes`` (Bug P3-5 fix).

        Shorthand schemes are auto-registered into ``_schemes`` at tool/prompt
        registration time inside ``app.py:_build_handler``.
        """
        result: list[dict[str, Any]] = []
        for requirement in security_config:
            if "type" in requirement:
                auth_type = requirement.get("type", "").lower()
                scopes = requirement.get("scopes", [])
                if auth_type == "bearer":
                    result.append({"bearerAuth": scopes})
                elif auth_type == "apikey":
                    key_name = requirement.get("key_name", "X-API-Key")
                    location = requirement.get("in", "header")
                    scheme_name = f"apiKeyAuth_{location}_{key_name}"
                    result.append({scheme_name: scopes})
                else:
                    result.append(requirement)
            else:
                result.append(requirement)
        return result
