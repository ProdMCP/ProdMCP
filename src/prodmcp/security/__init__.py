"""Security framework for ProdMCP.

Provides robust OpenMCP and FastAPI aligned security schemes.
"""

from ..dependencies import Depends
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
    "Depends",
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
