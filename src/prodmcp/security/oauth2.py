"""OAuth2 security schemes for ProdMCP."""

from __future__ import annotations

import logging
from typing import Any

from ..exceptions import ProdMCPSecurityError
from .base import SecurityContext, SecurityScheme

logger = logging.getLogger(__name__)


BEARER_PREFIX = "Bearer "
ERROR_MISSING_BEARER = "Missing or invalid OAuth2 Bearer token"

class OAuth2PasswordBearer(SecurityScheme):
    """OAuth2 Password flow via Bearer token."""

    scheme_type = "oauth2"

    def __init__(self, token_url: str, scopes: dict[str, str] | None = None) -> None:
        self.token_url = token_url
        self.scopes_description = scopes or {}

    def extract(self, context: dict[str, Any]) -> SecurityContext:
        headers: dict[str, str] = context.get("headers", {})
        auth_header = headers.get("authorization", headers.get("Authorization", ""))

        if not auth_header.startswith(BEARER_PREFIX):
            raise ProdMCPSecurityError(
                ERROR_MISSING_BEARER, scheme="oauth2"
            )

        token = auth_header[7:]
        return SecurityContext(token=token, scopes=list(self.scopes_description.keys()))

    def to_spec(self) -> dict[str, Any]:
        return {
            "type": "oauth2",
            "flows": {
                "password": {
                    "tokenUrl": self.token_url,
                    "scopes": self.scopes_description,
                }
            },
        }


class OAuth2AuthorizationCodeBearer(SecurityScheme):
    """OAuth2 Authorization Code flow via Bearer token."""

    scheme_type = "oauth2"

    def __init__(
        self,
        authorization_url: str,
        token_url: str,
        scopes: dict[str, str] | None = None,
    ) -> None:
        self.authorization_url = authorization_url
        self.token_url = token_url
        self.scopes_description = scopes or {}

    def extract(self, context: dict[str, Any]) -> SecurityContext:
        headers: dict[str, str] = context.get("headers", {})
        auth_header = headers.get("authorization", headers.get("Authorization", ""))

        if not auth_header.startswith(BEARER_PREFIX):
            raise ProdMCPSecurityError(
                ERROR_MISSING_BEARER, scheme="oauth2"
            )

        token = auth_header[7:]
        return SecurityContext(token=token, scopes=list(self.scopes_description.keys()))

    def to_spec(self) -> dict[str, Any]:
        return {
            "type": "oauth2",
            "flows": {
                "authorizationCode": {
                    "authorizationUrl": self.authorization_url,
                    "tokenUrl": self.token_url,
                    "scopes": self.scopes_description,
                }
            },
        }


class OAuth2ClientCredentialsBearer(SecurityScheme):
    """OAuth2 Client Credentials flow via Bearer token."""

    scheme_type = "oauth2"

    def __init__(
        self,
        token_url: str,
        scopes: dict[str, str] | None = None,
    ) -> None:
        self.token_url = token_url
        self.scopes_description = scopes or {}

    def extract(self, context: dict[str, Any]) -> SecurityContext:
        headers: dict[str, str] = context.get("headers", {})
        auth_header = headers.get("authorization", headers.get("Authorization", ""))

        if not auth_header.startswith(BEARER_PREFIX):
            raise ProdMCPSecurityError(
                ERROR_MISSING_BEARER, scheme="oauth2"
            )

        token = auth_header[7:]
        return SecurityContext(token=token, scopes=list(self.scopes_description.keys()))

    def to_spec(self) -> dict[str, Any]:
        return {
            "type": "oauth2",
            "flows": {
                "clientCredentials": {
                    "tokenUrl": self.token_url,
                    "scopes": self.scopes_description,
                }
            },
        }
