"""ProdMCP — FastAPI-like production layer for MCP.

Public API exports.
"""

from .app import ProdMCP
from .dependencies import Depends
from .exceptions import (
    ProdMCPError,
    ProdMCPMiddlewareError,
    ProdMCPSecurityError,
    ProdMCPValidationError,
)
from .middleware import LoggingMiddleware, Middleware, MiddlewareContext
from .openmcp import generate_spec, spec_to_json
from .schemas import resolve_schema, validate_data
from .security import (
    ApiKeyAuth,
    BearerAuth,
    CustomAuth,
    SecurityContext,
    SecurityManager,
    SecurityScheme,
)

__version__ = "0.1.0"

__all__ = [
    # Core
    "ProdMCP",
    # Security
    "BearerAuth",
    "ApiKeyAuth",
    "CustomAuth",
    "SecurityContext",
    "SecurityManager",
    "SecurityScheme",
    # Middleware
    "Middleware",
    "MiddlewareContext",
    "LoggingMiddleware",
    # Dependencies
    "Depends",
    # Schemas
    "resolve_schema",
    "validate_data",
    # Spec
    "generate_spec",
    "spec_to_json",
    # Exceptions
    "ProdMCPError",
    "ProdMCPValidationError",
    "ProdMCPSecurityError",
    "ProdMCPMiddlewareError",
]
