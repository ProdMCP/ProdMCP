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


# Bug 7 fix: re-export the most commonly needed ASGI middlewares so users never
# have to reach into fastapi/starlette directly.  These are guarded by try/except
# because Starlette ships with the [rest] extra, not the core install.
# When unavailable the names are set to None — accessing them at runtime will
# raise AttributeError with a clear message via `add_asgi_middleware`, which
# validates its arguments before calling the underlying ASGI stack.
try:
    from starlette.middleware.cors import CORSMiddleware
    from starlette.middleware.gzip import GZipMiddleware
    from starlette.middleware.trustedhost import TrustedHostMiddleware
except ImportError:
    CORSMiddleware = None   # type: ignore[assignment,misc]
    GZipMiddleware = None   # type: ignore[assignment,misc]
    TrustedHostMiddleware = None  # type: ignore[assignment,misc]


# D7 fix: derive version from the installed package metadata so __version__
# stays in sync with pyproject.toml automatically after each release bump.
# Fallback covers editable installs that haven't regenerated dist-info.
try:
    from importlib.metadata import version as _pkg_version
    __version__: str = _pkg_version("prodmcp")
except Exception:  # PackageNotFoundError or any import error
    __version__ = "0.3.7"

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
    # ASGI Middlewares (Bug 7: re-exported for fully ProdMCP-only codebases)
    "CORSMiddleware",
    "GZipMiddleware",
    "TrustedHostMiddleware",
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
    # Version
    "__version__",
]
