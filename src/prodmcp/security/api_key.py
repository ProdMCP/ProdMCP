"""API Key security schemes for ProdMCP."""

from __future__ import annotations

import logging
from typing import Any

from ..exceptions import ProdMCPSecurityError
from .base import SecurityContext, SecurityScheme

logger = logging.getLogger(__name__)


class APIKeyHeader(SecurityScheme):
    """API key authentication via header."""

    scheme_type = "apiKey"

    def __init__(self, name: str = "X-API-Key") -> None:
        self.name = name

    def extract(self, context: dict[str, Any]) -> SecurityContext:
        # N2 fix: HTTP headers are case-insensitive (RFC 7230).
        # Normalize all header keys to lowercase before lookup so that both
        # "X-API-Key" and "x-api-key" are found regardless of how the HTTP
        # framework presents them.
        headers: dict[str, str] = context.get("headers", {})
        lowered = {k.lower(): v for k, v in headers.items()}
        api_key = lowered.get(self.name.lower(), "")

        if not api_key:
            raise ProdMCPSecurityError(
                f"Missing API key in header: {self.name}",
                scheme="apiKey",
            )
        return SecurityContext(token=api_key, metadata={"key_name": self.name})

    def to_spec(self) -> dict[str, Any]:
        return {
            "type": "apiKey",
            "name": self.name,
            "in": "header",
        }


class APIKeyQuery(SecurityScheme):
    """API key authentication via query parameter."""

    scheme_type = "apiKey"

    def __init__(self, name: str = "api_key") -> None:
        self.name = name

    def extract(self, context: dict[str, Any]) -> SecurityContext:
        params: dict[str, str] = context.get("query_params", {})
        # C11 fix: use .get(name) returning None (not "") so we can distinguish
        # "key absent" from "key present but empty". Both are rejected, but give
        # different error messages to aid debugging.
        api_key = params.get(self.name)
        if api_key is None:
            raise ProdMCPSecurityError(
                f"Missing API key in query parameter: {self.name}",
                scheme="apiKey",
            )
        if not api_key:
            raise ProdMCPSecurityError(
                f"Empty API key in query parameter: {self.name}",
                scheme="apiKey",
            )
        return SecurityContext(token=api_key, metadata={"key_name": self.name})

    def to_spec(self) -> dict[str, Any]:
        return {
            "type": "apiKey",
            "name": self.name,
            "in": "query",
        }


class APIKeyCookie(SecurityScheme):
    """API key authentication via cookie."""

    scheme_type = "apiKey"

    def __init__(self, name: str) -> None:
        self.name = name

    def extract(self, context: dict[str, Any]) -> SecurityContext:
        cookies: dict[str, str] = context.get("cookies", {})
        # C11 fix: same as APIKeyQuery — distinguish absent vs empty cookie.
        api_key = cookies.get(self.name)
        if api_key is None:
            raise ProdMCPSecurityError(
                f"Missing API key in cookie: {self.name}",
                scheme="apiKey",
            )
        if not api_key:
            raise ProdMCPSecurityError(
                f"Empty API key in cookie: {self.name}",
                scheme="apiKey",
            )
        return SecurityContext(token=api_key, metadata={"key_name": self.name})

    def to_spec(self) -> dict[str, Any]:
        return {
            "type": "apiKey",
            "name": self.name,
            "in": "cookie",
        }


class ApiKeyAuth(SecurityScheme):
    """Backwards compatibility shim for older ApiKeyAuth."""

    scheme_type = "apiKey"

    def __init__(self, key_name: str = "X-API-Key", location: str = "header") -> None:
        self.key_name = key_name
        self.location = location
        if location == "header":
            self._impl = APIKeyHeader(name=key_name)
        elif location == "query":
            self._impl = APIKeyQuery(name=key_name)
        elif location == "cookie":
            self._impl = APIKeyCookie(name=key_name)
        else:
            raise ValueError(f"Invalid ApiKeyAuth location {location}")
        
    def extract(self, context: dict[str, Any]) -> SecurityContext:
        return self._impl.extract(context)

    def to_spec(self) -> dict[str, Any]:
        return self._impl.to_spec()
