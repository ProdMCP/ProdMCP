"""Security framework for ProdMCP.

Provides robust OpenMCP and FastAPI aligned security schemes.
"""

# E6 fix: Depends is a DI primitive, not a security primitive.
# It was removed from this package to eliminate upward coupling
# (security/ → dependencies) and the misleading API surface.
# Import it from `prodmcp` or `prodmcp.dependencies` instead.
from .api_key import APIKeyCookie, APIKeyHeader, APIKeyQuery, ApiKeyAuth
from .base import CustomAuth, SecurityContext, SecurityManager, SecurityScheme
from .http import HTTPBasicAuth, HTTPBearer, HTTPDigestAuth
from .oauth2 import (
    OAuth2AuthorizationCodeBearer,
    OAuth2ClientCredentialsBearer,
    OAuth2PasswordBearer,
)
from .open_id import OpenIdConnect

# Backwards compatibility names
BearerAuth = HTTPBearer

__all__ = [
    "APIKeyCookie",
    "APIKeyHeader",
    "APIKeyQuery",
    "ApiKeyAuth",
    "BearerAuth",
    "CustomAuth",
    "HTTPBasicAuth",
    "HTTPBearer",
    "HTTPDigestAuth",
    "OAuth2AuthorizationCodeBearer",
    "OAuth2ClientCredentialsBearer",
    "OAuth2PasswordBearer",
    "OpenIdConnect",
    "SecurityContext",
    "SecurityManager",
    "SecurityScheme",
]
