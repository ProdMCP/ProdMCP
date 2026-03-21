"""ProdMCP custom exceptions."""

from __future__ import annotations

from typing import Any


class ProdMCPError(Exception):
    """Base exception for all ProdMCP errors."""


class ProdMCPValidationError(ProdMCPError):
    """Raised when input or output validation fails."""

    def __init__(
        self,
        message: str,
        errors: list[dict[str, Any]] | None = None,
        *,
        field: str | None = None,
    ) -> None:
        self.errors = errors or []
        self.field = field
        super().__init__(message)

    def to_dict(self) -> dict[str, Any]:
        return {
            "error": "validation_error",
            "message": str(self),
            "field": self.field,
            "details": self.errors,
        }


class ProdMCPSecurityError(ProdMCPError):
    """Raised when a security check fails."""

    def __init__(
        self,
        message: str = "Authentication required",
        *,
        scheme: str | None = None,
    ) -> None:
        self.scheme = scheme
        super().__init__(message)

    def to_dict(self) -> dict[str, Any]:
        return {
            "error": "security_error",
            "message": str(self),
            "scheme": self.scheme,
        }


class ProdMCPMiddlewareError(ProdMCPError):
    """Raised when a middleware encounters an error."""
