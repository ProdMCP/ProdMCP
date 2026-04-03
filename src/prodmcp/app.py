"""ProdMCP — Unified production layer for API and MCP.

This module provides the central ``ProdMCP`` class that serves as a
drop-in replacement for both FastAPI and FastMCP, offering schema-driven
development, validation, security, middleware, dependency injection,
and OpenMCP spec generation.

Supports:
    - FastAPI-identical: @app.get(), @app.post(), @app.put(), @app.delete(), @app.patch()
    - FastMCP-identical: @app.tool(), @app.prompt(), @app.resource()
    - ProdMCP-original:  @app.common() for shared cross-cutting concerns
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from typing import Any, Callable, Type

from pydantic import BaseModel

from .dependencies import Depends, resolve_dependencies
from .middleware import Middleware, MiddlewareManager, build_middleware_chain
from .openmcp import generate_spec, spec_to_json
from .security import SecurityManager, SecurityScheme
from .validation import create_validated_handler

logger = logging.getLogger(__name__)

# Sentinel to distinguish "not provided" from None
_UNSET: Any = object()


def _merge_common(fn: Callable, key: str, explicit_value: Any) -> Any:
    """Return explicit_value if provided, else fall back to __prodmcp_common__."""
    if explicit_value is not _UNSET and explicit_value is not None:
        return explicit_value
    common = getattr(fn, "__prodmcp_common__", None)
    if common and key in common:
        return common[key]
    return None


class ProdMCP:
    """Central ProdMCP application.

    Drop-in replacement for both FastAPI and FastMCP.

    Accepts both constructor styles:
        ProdMCP("MyServer")                        # FastMCP style
        ProdMCP(title="MyServer", version="1.0")   # FastAPI style

    Args:
        name: Server name (positional, FastMCP style).
        title: Server title (keyword, FastAPI alias for name).
        version: Server version.
        description: Server description.
        strict_output: If True, output validation errors are raised globally.
        mcp_path: Sub-path to mount the MCP SSE endpoint (default "/mcp").
        **fastmcp_kwargs: Extra kwargs passed to FastMCP().
    """

    def __init__(
        self,
        name: str = "ProdMCP Server",
        *,
        title: str | None = None,
        version: str = "1.0.0",
        description: str = "",
        strict_output: bool = True,
        mcp_path: str = "/mcp",
        **fastmcp_kwargs: Any,
    ) -> None:
        # FastAPI uses 'title', FastMCP uses positional 'name'
        self.name = title or name
        self.version = version
        self.description = description
        self.strict_output = strict_output
        self.mcp_path = mcp_path
        self._fastmcp_kwargs = fastmcp_kwargs

        # Internal registry — stores metadata for all entities
        self._registry: dict[str, dict[str, dict[str, Any]]] = {
            "tools": {},
            "prompts": {},
            "resources": {},
            "api": {},
        }

        # Pending MCP registrations (deferred so @app.common() can run first)
        self._pending_tools: list[tuple[Callable, dict[str, Any]]] = []
        self._pending_prompts: list[tuple[Callable, dict[str, Any]]] = []
        self._pending_resources: list[tuple[Callable, dict[str, Any]]] = []

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

    def _finalize_pending(self) -> None:
        """Finalize all pending MCP registrations.

        Called lazily before run(), export_openmcp(), or test_mcp_as_fastapi().
        At this point all decorators (including @app.common()) have executed,
        so __prodmcp_common__ is available on functions.

        Uses a drain pattern — processes and clears pending lists each call,
        so new decorators added incrementally are still picked up.
        """
        while self._pending_tools:
            fn, opts = self._pending_tools.pop(0)
            self._register_tool(fn, **opts)

        while self._pending_prompts:
            fn, opts = self._pending_prompts.pop(0)
            self._register_prompt(fn, **opts)

        while self._pending_resources:
            fn, opts = self._pending_resources.pop(0)
            self._register_resource(fn, **opts)

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

    # ── Common Decorator (ProdMCP-original) ────────────────────────────

    def common(
        self,
        *,
        input_schema: Type[BaseModel] | dict[str, Any] | None = None,
        output_schema: Type[BaseModel] | dict[str, Any] | None = None,
        response_model: Type[BaseModel] | None = None,
        security: list[dict[str, Any]] | None = None,
        middleware: list[str | Middleware] | None = None,
        tags: set[str] | list[str] | None = None,
        strict: bool | None = None,
    ) -> Callable[..., Any]:
        """Decorator for shared cross-cutting concerns.

        Use this when stacking @app.tool() and @app.get()/@app.post() on the
        same function to avoid duplicating input_schema, security, etc.

        Usage:
            @app.common(input_schema=UserInput, security=[{"bearer": ["read"]}])
            @app.tool(name="get_user")
            @app.get("/users/{user_id}")
            def get_user(user_id: str) -> dict:
                ...
        """
        # response_model is a FastAPI alias for output_schema
        effective_output = output_schema or response_model

        def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
            fn.__prodmcp_common__ = {
                "input_schema": input_schema,
                "output_schema": effective_output,
                "security": security,
                "middleware": middleware,
                "tags": tags,
                "strict": strict,
            }
            return fn

        return decorator

    # ── MCP Decorators (FastMCP-identical) ──────────────────────────────

    def tool(
        self,
        name: str | None = None,
        *,
        description: str | None = None,
        input_schema: Type[BaseModel] | dict[str, Any] | None = _UNSET,
        output_schema: Type[BaseModel] | dict[str, Any] | None = _UNSET,
        security: list[dict[str, Any]] | None = _UNSET,
        middleware: list[str | Middleware] | None = _UNSET,
        tags: set[str] | None = _UNSET,
        strict: bool | None = _UNSET,
    ) -> Callable[..., Any]:
        """Decorator to register an MCP tool.

        When used alone, accepts all params inline (backward compatible).
        When stacked with @app.common(), merges shared config automatically.
        """

        def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
            # Defer registration so @app.common() can set __prodmcp_common__ first
            self._pending_tools.append((fn, {
                "name": name,
                "description": description,
                "input_schema": input_schema,
                "output_schema": output_schema,
                "security": security,
                "middleware": middleware,
                "tags": tags,
                "strict": strict,
            }))
            return fn

        return decorator

    def _register_tool(
        self,
        fn: Callable[..., Any],
        *,
        name: str | None,
        description: str | None,
        input_schema: Any,
        output_schema: Any,
        security: Any,
        middleware: Any,
        tags: Any,
        strict: Any,
    ) -> None:
        """Actually register a tool with FastMCP (called during finalization)."""
        eff_input = _merge_common(fn, "input_schema", input_schema)
        eff_output = _merge_common(fn, "output_schema", output_schema)
        eff_security = _merge_common(fn, "security", security)
        eff_middleware = _merge_common(fn, "middleware", middleware)
        eff_tags = _merge_common(fn, "tags", tags)
        eff_strict_val = _merge_common(fn, "strict", strict)

        tool_name = name or fn.__name__
        tool_desc = description or fn.__doc__ or ""
        is_strict = eff_strict_val if eff_strict_val is not None else self.strict_output

        # Build the wrapped handler
        wrapped = self._build_handler(
            fn,
            entity_type="tool",
            entity_name=tool_name,
            input_schema=eff_input,
            output_schema=eff_output,
            security_config=eff_security,
            entity_middleware=eff_middleware,
            strict=is_strict,
        )

        # Store metadata
        self._registry["tools"][tool_name] = {
            "name": tool_name,
            "description": tool_desc.strip(),
            "input_schema": eff_input,
            "output_schema": eff_output,
            "security": getattr(wrapped, "__security_config__", eff_security or []),
            "middleware": eff_middleware or [],
            "tags": eff_tags,
            "handler": fn,
            "strict": is_strict,
        }

        # Register with FastMCP
        self.mcp.tool(
            name=tool_name,
            description=tool_desc.strip(),
        )(wrapped)

    def prompt(
        self,
        name: str | None = None,
        *,
        description: str | None = None,
        input_schema: Type[BaseModel] | dict[str, Any] | None = _UNSET,
        output_schema: Type[BaseModel] | dict[str, Any] | None = _UNSET,
        tags: set[str] | None = _UNSET,
    ) -> Callable[..., Any]:
        """Decorator to register an MCP prompt."""

        def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
            self._pending_prompts.append((fn, {
                "name": name,
                "description": description,
                "input_schema": input_schema,
                "output_schema": output_schema,
                "tags": tags,
            }))
            return fn

        return decorator

    def _register_prompt(
        self,
        fn: Callable[..., Any],
        *,
        name: str | None,
        description: str | None,
        input_schema: Any,
        output_schema: Any,
        tags: Any,
    ) -> None:
        """Actually register a prompt with FastMCP (called during finalization)."""
        eff_input = _merge_common(fn, "input_schema", input_schema)
        eff_output = _merge_common(fn, "output_schema", output_schema)
        eff_tags = _merge_common(fn, "tags", tags)

        prompt_name = name or fn.__name__
        prompt_desc = description or fn.__doc__ or ""

        self._registry["prompts"][prompt_name] = {
            "name": prompt_name,
            "description": prompt_desc.strip(),
            "input_schema": eff_input,
            "output_schema": eff_output,
            "tags": eff_tags,
            "handler": fn,
        }

        wrapped = create_validated_handler(
            fn,
            input_schema=eff_input,
            output_schema=eff_output,
            strict=False,
        )

        self.mcp.prompt(
            name=prompt_name,
            description=prompt_desc.strip(),
        )(wrapped)

    def resource(
        self,
        uri: str | None = None,
        *,
        name: str | None = None,
        description: str | None = None,
        output_schema: Type[BaseModel] | dict[str, Any] | None = _UNSET,
        tags: set[str] | None = _UNSET,
        mime_type: str | None = None,
    ) -> Callable[..., Any]:
        """Decorator to register an MCP resource."""

        def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
            self._pending_resources.append((fn, {
                "uri": uri,
                "name": name,
                "description": description,
                "output_schema": output_schema,
                "tags": tags,
                "mime_type": mime_type,
            }))
            return fn

        return decorator

    def _register_resource(
        self,
        fn: Callable[..., Any],
        *,
        uri: str | None,
        name: str | None,
        description: str | None,
        output_schema: Any,
        tags: Any,
        mime_type: str | None,
    ) -> None:
        """Actually register a resource with FastMCP (called during finalization)."""
        eff_output = _merge_common(fn, "output_schema", output_schema)
        eff_tags = _merge_common(fn, "tags", tags)

        resource_name = name or fn.__name__
        resource_desc = description or fn.__doc__ or ""
        resource_uri = uri or f"resource://{resource_name}"

        self._registry["resources"][resource_name] = {
            "name": resource_name,
            "description": resource_desc.strip(),
            "uri": resource_uri,
            "output_schema": eff_output,
            "tags": eff_tags,
            "handler": fn,
        }

        wrapped = create_validated_handler(
            fn,
            output_schema=eff_output,
            strict=False,
        )

        fastmcp_kwargs: dict[str, Any] = {
            "name": resource_name,
            "description": resource_desc.strip(),
        }
        if mime_type:
            fastmcp_kwargs["mime_type"] = mime_type

        self.mcp.resource(resource_uri, **fastmcp_kwargs)(wrapped)

    # ── HTTP Method Decorators (FastAPI-identical) ──────────────────────

    def _http_method(
        self,
        method: str,
        path: str,
        *,
        response_model: Type[BaseModel] | None = None,
        status_code: int | None = None,
        tags: list[str] | None = None,
        summary: str | None = None,
        description: str | None = None,
        dependencies: list | None = None,
        deprecated: bool = False,
        operation_id: str | None = None,
        include_in_schema: bool = True,
        response_class: Any = None,
        responses: dict | None = None,
        response_description: str | None = None,
    ) -> Callable[..., Any]:
        """Internal method to register an HTTP route (FastAPI-style)."""

        default_status = {
            "GET": 200, "POST": 201, "PUT": 200,
            "DELETE": 204, "PATCH": 200,
        }

        def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
            # Note: @app.common() may not have run yet (decorator ordering).
            # We store a reference to fn and resolve common config lazily
            # when the route is actually built in create_unified_app().
            resolved_status = status_code if status_code is not None else default_status.get(method.upper(), 200)

            registry_key = f"{path}:{method.upper()}"
            self._registry["api"][registry_key] = {
                "path": path,
                "method": method.upper(),
                "handler": fn,
                "response_model": response_model,
                "status_code": resolved_status,
                "tags": tags,
                "summary": summary or fn.__doc__,
                "description": description,
                "dependencies": dependencies,
                "deprecated": deprecated,
                "operation_id": operation_id,
                "include_in_schema": include_in_schema,
                "response_class": response_class,
                "responses": responses,
                "response_description": response_description,
                # These will be resolved from __prodmcp_common__ at build time
                "_resolve_common": True,
            }

            return fn

        return decorator

    def get(
        self,
        path: str,
        *,
        response_model: Type[BaseModel] | None = None,
        status_code: int | None = None,
        tags: list[str] | None = None,
        summary: str | None = None,
        description: str | None = None,
        dependencies: list | None = None,
        deprecated: bool = False,
        operation_id: str | None = None,
        include_in_schema: bool = True,
        response_class: Any = None,
        responses: dict | None = None,
        response_description: str | None = None,
    ) -> Callable[..., Any]:
        """Register a GET route (FastAPI-identical signature)."""
        return self._http_method(
            "GET", path,
            response_model=response_model, status_code=status_code,
            tags=tags, summary=summary, description=description,
            dependencies=dependencies, deprecated=deprecated,
            operation_id=operation_id, include_in_schema=include_in_schema,
            response_class=response_class, responses=responses,
            response_description=response_description,
        )

    def post(
        self,
        path: str,
        *,
        response_model: Type[BaseModel] | None = None,
        status_code: int | None = None,
        tags: list[str] | None = None,
        summary: str | None = None,
        description: str | None = None,
        dependencies: list | None = None,
        deprecated: bool = False,
        operation_id: str | None = None,
        include_in_schema: bool = True,
        response_class: Any = None,
        responses: dict | None = None,
        response_description: str | None = None,
    ) -> Callable[..., Any]:
        """Register a POST route (FastAPI-identical signature)."""
        return self._http_method(
            "POST", path,
            response_model=response_model, status_code=status_code,
            tags=tags, summary=summary, description=description,
            dependencies=dependencies, deprecated=deprecated,
            operation_id=operation_id, include_in_schema=include_in_schema,
            response_class=response_class, responses=responses,
            response_description=response_description,
        )

    def put(
        self,
        path: str,
        *,
        response_model: Type[BaseModel] | None = None,
        status_code: int | None = None,
        tags: list[str] | None = None,
        summary: str | None = None,
        description: str | None = None,
        dependencies: list | None = None,
        deprecated: bool = False,
        operation_id: str | None = None,
        include_in_schema: bool = True,
        response_class: Any = None,
        responses: dict | None = None,
        response_description: str | None = None,
    ) -> Callable[..., Any]:
        """Register a PUT route (FastAPI-identical signature)."""
        return self._http_method(
            "PUT", path,
            response_model=response_model, status_code=status_code,
            tags=tags, summary=summary, description=description,
            dependencies=dependencies, deprecated=deprecated,
            operation_id=operation_id, include_in_schema=include_in_schema,
            response_class=response_class, responses=responses,
            response_description=response_description,
        )

    def delete(
        self,
        path: str,
        *,
        response_model: Type[BaseModel] | None = None,
        status_code: int | None = None,
        tags: list[str] | None = None,
        summary: str | None = None,
        description: str | None = None,
        dependencies: list | None = None,
        deprecated: bool = False,
        operation_id: str | None = None,
        include_in_schema: bool = True,
        response_class: Any = None,
        responses: dict | None = None,
        response_description: str | None = None,
    ) -> Callable[..., Any]:
        """Register a DELETE route (FastAPI-identical signature)."""
        return self._http_method(
            "DELETE", path,
            response_model=response_model, status_code=status_code,
            tags=tags, summary=summary, description=description,
            dependencies=dependencies, deprecated=deprecated,
            operation_id=operation_id, include_in_schema=include_in_schema,
            response_class=response_class, responses=responses,
            response_description=response_description,
        )

    def patch(
        self,
        path: str,
        *,
        response_model: Type[BaseModel] | None = None,
        status_code: int | None = None,
        tags: list[str] | None = None,
        summary: str | None = None,
        description: str | None = None,
        dependencies: list | None = None,
        deprecated: bool = False,
        operation_id: str | None = None,
        include_in_schema: bool = True,
        response_class: Any = None,
        responses: dict | None = None,
        response_description: str | None = None,
    ) -> Callable[..., Any]:
        """Register a PATCH route (FastAPI-identical signature)."""
        return self._http_method(
            "PATCH", path,
            response_model=response_model, status_code=status_code,
            tags=tags, summary=summary, description=description,
            dependencies=dependencies, deprecated=deprecated,
            operation_id=operation_id, include_in_schema=include_in_schema,
            response_class=response_class, responses=responses,
            response_description=response_description,
        )

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
        import functools
        from .security import SecurityScheme

        security_config = list(security_config) if security_config else []
        sig = inspect.signature(fn)
        new_params = []
        has_dependencies = False

        for name, param in sig.parameters.items():
            if isinstance(param.default, Depends):
                has_dependencies = True
                dep = param.default.dependency
                if isinstance(dep, SecurityScheme):
                    scheme_name = f"auto_{dep.scheme_type}_{id(dep)}"
                    self.add_security_scheme(scheme_name, dep)
                    scopes = getattr(dep, "scopes", []) 
                    if hasattr(dep, "scopes_description"):
                        scopes = list(dep.scopes_description.keys())
                    security_config.append({scheme_name: scopes})
            else:
                new_params.append(param)

        stripped_sig = sig.replace(parameters=new_params)

        if has_dependencies:
            @functools.wraps(fn)
            async def dep_wrapper(*args: Any, **kwargs: Any) -> Any:
                context = kwargs.pop("__request_context__", {})
                kwargs.pop("__security_context__", None)
                
                resolved = await resolve_dependencies(fn, context, overrides=kwargs)
                kwargs.update(resolved)
                
                if asyncio.iscoroutinefunction(fn):
                    return await fn(*args, **kwargs)
                return fn(*args, **kwargs)
            
            dep_wrapper.__signature__ = stripped_sig
            handler = dep_wrapper
        else:
            handler = fn
            handler.__signature__ = stripped_sig

        # 1. Validation wrapping
        handler = create_validated_handler(
            handler,
            input_schema=input_schema,
            output_schema=output_schema,
            strict=strict,
        )
        setattr(handler, "__has_dependencies__", has_dependencies)

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

        setattr(handler, "__security_config__", security_config)

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
            context = kwargs.pop("__security_context__", {})
            security_mgr.check(context, security_config)
            
            if getattr(handler, "__has_dependencies__", False):
                kwargs["__request_context__"] = context
                
            if "__security_context__" in inspect.signature(handler).parameters:
                kwargs["__security_context__"] = context
            
            if asyncio.iscoroutinefunction(handler):
                return await handler(**kwargs)
            return handler(**kwargs)

        secured.__signature__ = inspect.signature(handler)
        return secured

    # ── OpenMCP Export ─────────────────────────────────────────────────

    def export_openmcp(self) -> dict[str, Any]:
        """Generate and return the OpenMCP specification as a dict."""
        self._finalize_pending()
        return generate_spec(self)

    def export_openmcp_json(self, indent: int = 2) -> str:
        """Generate and return the OpenMCP specification as a JSON string."""
        self._finalize_pending()
        return spec_to_json(generate_spec(self), indent=indent)

    # ── FastAPI Bridge (MCP Testing) ─────────────────────────────────

    def test_mcp_as_fastapi(self) -> Any:
        """Return a FastAPI app that auto-maps all MCP tools/prompts/resources to REST routes.

        This is useful for testing your MCP handlers via standard HTTP tools
        (curl, Postman, Swagger UI) without using an MCP client.

        Tools   → POST /tools/{name}
        Prompts → POST /prompts/{name}
        Resources → GET /resources/{uri}
        """
        self._finalize_pending()
        from .fastapi import create_fastapi_app
        return create_fastapi_app(self)

    # Backward compatibility alias
    as_fastapi = test_mcp_as_fastapi

    # ── Run ────────────────────────────────────────────────────────────

    def run(
        self,
        *,
        host: str = "0.0.0.0",
        port: int = 8000,
        transport: str = "unified",
        **kwargs: Any,
    ) -> None:
        """Start the server.

        Args:
            host: Bind address (default "0.0.0.0").
            port: Port number (default 8000).
            transport: One of "unified" (default), "stdio", or "sse".
                - "unified": Serves both REST API and MCP on one HTTP server.
                  REST routes at /, MCP SSE at {mcp_path}/sse.
                - "stdio": Pure MCP over stdin/stdout (legacy, local subprocess).
                - "sse": Pure MCP SSE server (no REST routes).
            **kwargs: Additional kwargs passed through.
        """
        self._finalize_pending()

        if transport == "stdio":
            self.mcp.run(transport="stdio", **kwargs)
        elif transport == "sse":
            self.mcp.run(transport="sse", host=host, port=port, **kwargs)
        else:
            # Unified mode: REST + MCP on same server
            from .router import create_unified_app
            app = create_unified_app(self)
            try:
                import uvicorn
            except ImportError:
                raise ImportError(
                    "uvicorn is required for the unified server. "
                    "Install it with `pip install prodmcp[rest]`."
                )
            uvicorn.run(app, host=host, port=port, **kwargs)

    # ── Introspection ──────────────────────────────────────────────────

    def list_tools(self) -> list[str]:
        """Return names of all registered tools."""
        self._finalize_pending()
        return list(self._registry["tools"].keys())

    def list_prompts(self) -> list[str]:
        """Return names of all registered prompts."""
        self._finalize_pending()
        return list(self._registry["prompts"].keys())

    def list_resources(self) -> list[str]:
        """Return names of all registered resources."""
        self._finalize_pending()
        return list(self._registry["resources"].keys())

    def list_api_routes(self) -> list[str]:
        """Return keys of all registered API routes."""
        return list(self._registry["api"].keys())

    def get_tool_meta(self, name: str) -> dict[str, Any] | None:
        """Return metadata for a registered tool."""
        self._finalize_pending()
        return self._registry["tools"].get(name)

    def get_prompt_meta(self, name: str) -> dict[str, Any] | None:
        """Return metadata for a registered prompt."""
        self._finalize_pending()
        return self._registry["prompts"].get(name)

    def get_resource_meta(self, name: str) -> dict[str, Any] | None:
        """Return metadata for a registered resource."""
        self._finalize_pending()
        return self._registry["resources"].get(name)
