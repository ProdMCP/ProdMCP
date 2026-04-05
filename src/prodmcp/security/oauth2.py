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
    """OAuth2 Password flow via Bearer token.

    Args:
        token_url: Token endpoint URL.
        scopes: Dict of scope_name -> description.
        scope_validator: Optional callable ``(token: str) -> list[str]``.
    """

    scheme_type = "oauth2"

    def __init__(
        self,
        token_url: str,
        scopes: dict[str, str] | None = None,
        scope_validator: Any | None = None,
    ) -> None:
        self.token_url = token_url
        self.scopes_description = scopes or {}
        self.scope_validator = scope_validator
        # Bug P3-3 fix: emit warning once at construction, not per request.
        if self.scopes_description and scope_validator is None:
            import warnings
            warnings.warn(
                f"OAuth2PasswordBearer has scopes {list(self.scopes_description)!r} "
                "but no scope_validator — scope enforcement is DISABLED.",
                UserWarning, stacklevel=2,
            )

    def extract(self, context: dict[str, Any]) -> SecurityContext:
        headers: dict[str, str] = context.get("headers", {})
        auth_header = headers.get("authorization", headers.get("Authorization", ""))

        if not auth_header.startswith(BEARER_PREFIX):
            raise ProdMCPSecurityError(
                ERROR_MISSING_BEARER, scheme="oauth2"
            )

        token = auth_header[len(BEARER_PREFIX):]
        if self.scope_validator is not None:
            actual_scopes = self.scope_validator(token)
        elif self.scopes_description:
            actual_scopes = list(self.scopes_description.keys())
        else:
            actual_scopes = []
        return SecurityContext(token=token, scopes=actual_scopes)

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
        scope_validator: Any | None = None,
    ) -> None:
        self.authorization_url = authorization_url
        self.token_url = token_url
        self.scopes_description = scopes or {}
        self.scope_validator = scope_validator
        # Bug P3-3 fix: emit warning once at construction, not per request.
        if self.scopes_description and scope_validator is None:
            import warnings
            warnings.warn(
                f"OAuth2AuthorizationCodeBearer has scopes {list(self.scopes_description)!r} "
                "but no scope_validator — scope enforcement is DISABLED.",
                UserWarning, stacklevel=2,
            )

    def extract(self, context: dict[str, Any]) -> SecurityContext:
        headers: dict[str, str] = context.get("headers", {})
        auth_header = headers.get("authorization", headers.get("Authorization", ""))

        if not auth_header.startswith(BEARER_PREFIX):
            raise ProdMCPSecurityError(
                ERROR_MISSING_BEARER, scheme="oauth2"
            )

        token = auth_header[len(BEARER_PREFIX):]
        if self.scope_validator is not None:
            actual_scopes = self.scope_validator(token)
        elif self.scopes_description:
            actual_scopes = list(self.scopes_description.keys())
        else:
            actual_scopes = []
        return SecurityContext(token=token, scopes=actual_scopes)

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
        scope_validator: Any | None = None,
    ) -> None:
        self.token_url = token_url
        self.scopes_description = scopes or {}
        self.scope_validator = scope_validator
        # Bug P3-3 fix: emit warning once at construction, not per request.
        if self.scopes_description and scope_validator is None:
            import warnings
            warnings.warn(
                f"OAuth2ClientCredentialsBearer has scopes {list(self.scopes_description)!r} "
                "but no scope_validator — scope enforcement is DISABLED.",
                UserWarning, stacklevel=2,
            )

    def extract(self, context: dict[str, Any]) -> SecurityContext:
        headers: dict[str, str] = context.get("headers", {})
        auth_header = headers.get("authorization", headers.get("Authorization", ""))

        if not auth_header.startswith(BEARER_PREFIX):
            raise ProdMCPSecurityError(
                ERROR_MISSING_BEARER, scheme="oauth2"
            )

        token = auth_header[len(BEARER_PREFIX):]
        if self.scope_validator is not None:
            actual_scopes = self.scope_validator(token)
        elif self.scopes_description:
            actual_scopes = list(self.scopes_description.keys())
        else:
            actual_scopes = []
        return SecurityContext(token=token, scopes=actual_scopes)

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
