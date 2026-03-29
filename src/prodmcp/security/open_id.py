"""OpenID Connect security schemes for ProdMCP."""

from __future__ import annotations

import logging
from typing import Any

from ..exceptions import ProdMCPSecurityError
from .base import SecurityContext, SecurityScheme

logger = logging.getLogger(__name__)


class OpenIdConnect(SecurityScheme):
    """OpenID Connect authentication."""

    scheme_type = "openIdConnect"

    def __init__(self, openIdConnectUrl: str) -> None:
        self.openIdConnectUrl = openIdConnectUrl

    def extract(self, context: dict[str, Any]) -> SecurityContext:
        headers: dict[str, str] = context.get("headers", {})
        auth_header = headers.get("authorization", headers.get("Authorization", ""))

        if not auth_header.startswith("Bearer "):
            raise ProdMCPSecurityError(
                "Missing or invalid OpenID Connect Bearer token", scheme="openIdConnect"
            )

        token = auth_header[7:]
        return SecurityContext(token=token)

    def to_spec(self) -> dict[str, Any]:
        return {
            "type": "openIdConnect",
            "openIdConnectUrl": self.openIdConnectUrl,
        }
