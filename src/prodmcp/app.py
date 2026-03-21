"""ProdMCP — FastAPI-like production layer on top of FastMCP.

This module provides the central ``ProdMCP`` class that wraps FastMCP
with schema-driven development, validation, security, middleware,
dependency injection, and OpenMCP spec generation.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from typing import Any, Callable, Type

from pydantic import BaseModel

from .dependencies import Depends, resolve_dependencies
from .exceptions import ProdMCPSecurityError, ProdMCPValidationError
from .middleware import Middleware, MiddlewareManager, build_middleware_chain
from .openmcp import generate_spec, spec_to_json
from .schemas import resolve_schema, validate_data
from .security import SecurityManager, SecurityScheme
from .validation import create_validated_handler

logger = logging.getLogger(__name__)


class ProdMCP:
    """Central ProdMCP application.

    Wraps a FastMCP instance with additional layers for schema validation,
    security, middleware, dependency injection, and OpenMCP spec generation.

    Args:
        name: Server name.
        version: Server version.
        description: Server description.
        strict_output: If True, output validation errors are raised globally.
        **fastmcp_kwargs: Extra kwargs passed to FastMCP().
    """

    def __init__(
        self,
        name: str = "ProdMCP Server",
        *,
        version: str = "1.0.0",
        description: str = "",
        strict_output: bool = True,
        **fastmcp_kwargs: Any,
    ) -> None:
        self.name = name
        self.version = version
        self.description = description
        self.strict_output = strict_output
        self._fastmcp_kwargs = fastmcp_kwargs

        # Internal registry — stores metadata for all entities
        self._registry: dict[str, dict[str, dict[str, Any]]] = {
            "tools": {},
            "prompts": {},
            "resources": {},
        }

        # Managers
        self._security_manager = SecurityManager()
        self._middleware_manager = MiddlewareManager()

        # Lazy FastMCP instance
        self._mcp: Any = None

    @property
    def mcp(self) -> Any:
        """Lazily create and return the underlying FastMCP instance."""
        if self._mcp is None:
            from fastmcp import FastMCP

            self._mcp = FastMCP(
                name=self.name,
                **self._fastmcp_kwargs,
            )
        return self._mcp

    # ── Middleware API ──────────────────────────────────────────────────

    def add_middleware(
        self,
        middleware: Middleware | type,
        name: str | None = None,
    ) -> None:
        """Register global middleware.

        Args:
            middleware: A Middleware instance or class.
            name: Optional name for per-entity referencing.
        """
        self._middleware_manager.add(middleware, name=name)

    # ── Security API ───────────────────────────────────────────────────

    def add_security_scheme(self, name: str, scheme: SecurityScheme) -> None:
        """Register a named security scheme.

        Args:
            name: Scheme name (e.g., 'bearerAuth').
            scheme: SecurityScheme instance.
        """
        self._security_manager.register_scheme(name, scheme)

    # ── Decorator API ──────────────────────────────────────────────────

    def tool(
        self,
        name: str | None = None,
        *,
        description: str | None = None,
        input_schema: Type[BaseModel] | dict[str, Any] | None = None,
        output_schema: Type[BaseModel] | dict[str, Any] | None = None,
        security: list[dict[str, Any]] | None = None,
        middleware: list[str | Middleware] | None = None,
        tags: set[str] | None = None,
        strict: bool | None = None,
    ) -> Callable[..., Any]:
        """Decorator to register a tool.

        Usage:
            @app.tool(name="get_user", input_schema=UserInput, output_schema=UserOutput)
            def get_user(user_id: str) -> dict:
                ...
        """

        def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
            tool_name = name or fn.__name__
            tool_desc = description or fn.__doc__ or ""
            is_strict = strict if strict is not None else self.strict_output

            # Store metadata
            self._registry["tools"][tool_name] = {
                "name": tool_name,
                "description": tool_desc.strip(),
                "input_schema": input_schema,
                "output_schema": output_schema,
                "security": security or [],
                "middleware": middleware or [],
                "tags": tags,
                "handler": fn,
                "strict": is_strict,
            }

            # Build the wrapped handler
            wrapped = self._build_handler(
                fn,
                entity_type="tool",
                entity_name=tool_name,
                input_schema=input_schema,
                output_schema=output_schema,
                security_config=security,
                entity_middleware=middleware,
                strict=is_strict,
            )

            # Register with FastMCP
            self.mcp.tool(
                name=tool_name,
                description=tool_desc.strip(),
            )(wrapped)

            return fn

        return decorator

    def prompt(
        self,
        name: str | None = None,
        *,
        description: str | None = None,
        input_schema: Type[BaseModel] | dict[str, Any] | None = None,
        output_schema: Type[BaseModel] | dict[str, Any] | None = None,
        tags: set[str] | None = None,
    ) -> Callable[..., Any]:
        """Decorator to register a prompt.

        Usage:
            @app.prompt(name="summarize", input_schema=TextInput)
            def summarize(text: str) -> str:
                ...
        """

        def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
            prompt_name = name or fn.__name__
            prompt_desc = description or fn.__doc__ or ""

            self._registry["prompts"][prompt_name] = {
                "name": prompt_name,
                "description": prompt_desc.strip(),
                "input_schema": input_schema,
                "output_schema": output_schema,
                "tags": tags,
                "handler": fn,
            }

            # Wrap with validation (prompts typically don't need security/middleware)
            wrapped = create_validated_handler(
                fn,
                input_schema=input_schema,
                output_schema=output_schema,
                strict=False,
            )

            # Register with FastMCP
            self.mcp.prompt(
                name=prompt_name,
                description=prompt_desc.strip(),
            )(wrapped)

            return fn

        return decorator

    def resource(
        self,
        uri: str | None = None,
        *,
        name: str | None = None,
        description: str | None = None,
        output_schema: Type[BaseModel] | dict[str, Any] | None = None,
        tags: set[str] | None = None,
        mime_type: str | None = None,
    ) -> Callable[..., Any]:
        """Decorator to register a resource.

        Usage:
            @app.resource(uri="data://users", name="user_db", output_schema=UserData)
            def fetch_users() -> list:
                ...
        """

        def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
            resource_name = name or fn.__name__
            resource_desc = description or fn.__doc__ or ""
            resource_uri = uri or f"resource://{resource_name}"

            self._registry["resources"][resource_name] = {
                "name": resource_name,
                "description": resource_desc.strip(),
                "uri": resource_uri,
                "output_schema": output_schema,
                "tags": tags,
                "handler": fn,
            }

            # Wrap with output validation
            wrapped = create_validated_handler(
                fn,
                output_schema=output_schema,
                strict=False,
            )

            # Register with FastMCP
            fastmcp_kwargs: dict[str, Any] = {
                "name": resource_name,
                "description": resource_desc.strip(),
            }
            if mime_type:
                fastmcp_kwargs["mime_type"] = mime_type

            self.mcp.resource(resource_uri, **fastmcp_kwargs)(wrapped)

            return fn

        return decorator

    # ── Handler Building ───────────────────────────────────────────────

    def _build_handler(
        self,
        fn: Callable[..., Any],
        *,
        entity_type: str,
        entity_name: str,
        input_schema: Type[BaseModel] | dict[str, Any] | None = None,
        output_schema: Type[BaseModel] | dict[str, Any] | None = None,
        security_config: list[dict[str, Any]] | None = None,
        entity_middleware: list[str | Middleware] | None = None,
        strict: bool = True,
    ) -> Callable[..., Any]:
        """Build a fully wrapped handler with validation, security, and middleware."""
        # 1. Validation wrapping
        handler = create_validated_handler(
            fn,
            input_schema=input_schema,
            output_schema=output_schema,
            strict=strict,
        )

        # 2. Security wrapping
        if security_config:
            handler = self._wrap_with_security(handler, security_config)

        # 3. Middleware wrapping
        handler = build_middleware_chain(
            handler,
            self._middleware_manager,
            entity_middleware,
            entity_type,
            entity_name,
        )

        return handler

    def _wrap_with_security(
        self,
        handler: Callable[..., Any],
        security_config: list[dict[str, Any]],
    ) -> Callable[..., Any]:
        """Wrap a handler with security checks."""
        import functools

        security_mgr = self._security_manager

        @functools.wraps(handler)
        async def secured(**kwargs: Any) -> Any:
            # Extract context from kwargs if available
            context = kwargs.pop("__security_context__", {})
            security_mgr.check(context, security_config)
            if asyncio.iscoroutinefunction(handler):
                return await handler(**kwargs)
            return handler(**kwargs)

        secured.__signature__ = inspect.signature(handler)
        return secured

    # ── OpenMCP Export ─────────────────────────────────────────────────

    def export_openmcp(self) -> dict[str, Any]:
        """Generate and return the OpenMCP specification as a dict."""
        return generate_spec(self)

    def export_openmcp_json(self, indent: int = 2) -> str:
        """Generate and return the OpenMCP specification as a JSON string."""
        return spec_to_json(generate_spec(self), indent=indent)

    # ── Run ────────────────────────────────────────────────────────────

    def run(self, **kwargs: Any) -> None:
        """Start the MCP server (delegates to FastMCP.run)."""
        self.mcp.run(**kwargs)

    # ── Introspection ──────────────────────────────────────────────────

    def list_tools(self) -> list[str]:
        """Return names of all registered tools."""
        return list(self._registry["tools"].keys())

    def list_prompts(self) -> list[str]:
        """Return names of all registered prompts."""
        return list(self._registry["prompts"].keys())

    def list_resources(self) -> list[str]:
        """Return names of all registered resources."""
        return list(self._registry["resources"].keys())

    def get_tool_meta(self, name: str) -> dict[str, Any] | None:
        """Return metadata for a registered tool."""
        return self._registry["tools"].get(name)

    def get_prompt_meta(self, name: str) -> dict[str, Any] | None:
        """Return metadata for a registered prompt."""
        return self._registry["prompts"].get(name)

    def get_resource_meta(self, name: str) -> dict[str, Any] | None:
        """Return metadata for a registered resource."""
        return self._registry["resources"].get(name)
