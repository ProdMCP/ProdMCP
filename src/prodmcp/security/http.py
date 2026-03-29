"""HTTP security schemes for ProdMCP."""

from __future__ import annotations

import base64
import logging
from typing import Any

from ..exceptions import ProdMCPSecurityError
from .base import SecurityContext, SecurityScheme

logger = logging.getLogger(__name__)


class HTTPBearer(SecurityScheme):
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
            prefix, encoded = auth_header.split(" ", 1)
            decoded = base64.b64decode(encoded).decode("utf-8")
            username, password = decoded.split(":", 1)
        except Exception as e:
            raise ProdMCPSecurityError(
                "Invalid Basic authentication credentials", scheme="basicAuth"
            ) from e

        return SecurityContext(
            token=password, 
            metadata={"username": username, "password": password}
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

        token = auth_header[7:]
        return SecurityContext(token=token)

    def to_spec(self) -> dict[str, Any]:
        return {
            "type": "http",
            "scheme": "digest",
        }
