"""ProdMCP — Unified production layer for API and MCP.

Drop-in replacement for both FastAPI and FastMCP.

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

# Re-export HTTPException for FastAPI migration compatibility
try:
    from fastapi import HTTPException
except ImportError:
    # If FastAPI is not installed, provide a basic fallback
    class HTTPException(Exception):  # type: ignore[no-redef]
        """Fallback HTTPException when FastAPI is not installed."""
        def __init__(self, status_code: int = 500, detail: str = "") -> None:
            self.status_code = status_code
            self.detail = detail
            super().__init__(detail)


__version__ = "0.3.0"

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
    # HTTP Compat
    "HTTPException",
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
