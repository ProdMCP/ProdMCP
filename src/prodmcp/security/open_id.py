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

    def __init__(self, open_id_connect_url: str) -> None:
        self.open_id_connect_url = open_id_connect_url

    def extract(self, context: dict[str, Any]) -> SecurityContext:
        headers: dict[str, str] = context.get("headers", {})
        auth_header = headers.get("authorization", headers.get("Authorization", ""))

        if not auth_header.startswith("Bearer "):
            raise ProdMCPSecurityError(
                "Missing or invalid OpenID Connect Bearer token", scheme="openIdConnect"
            )

        # C4 fix: use len(prefix) instead of hardcoded 7 — consistent with B9 fixes
        # in http.py and oauth2.py. "Bearer " is 7 chars but the literal integer is fragile.
        token = auth_header[len("Bearer "):]
        return SecurityContext(token=token)

    def to_spec(self) -> dict[str, Any]:
        return {
            "type": "openIdConnect",
            "openIdConnectUrl": self.open_id_connect_url,
        }
