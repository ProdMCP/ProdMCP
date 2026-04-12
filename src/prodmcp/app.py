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
    """Return explicit_value if provided, else fall back to __prodmcp_common__.

    Uses ``_UNSET`` as the only sentinel — ``None``, ``False``, ``0``, and ``[]``
    are all considered explicit values and are returned as-is.  This prevents
    truthiness checks from silently discarding valid falsy overrides such as
    ``strict=False`` on a tool that inherits ``strict=True`` from ``@common()``.
    """
    if explicit_value is not _UNSET:
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

        # Global exception handlers — applied to the FastAPI app by create_unified_app()
        # and create_fastapi_app() after building the fresh FastAPI instance.
        # Each entry is a (exc_class_or_status_code, handler_callable) tuple.
        self._exception_handlers: list[tuple[Any, Any]] = []

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
        # D5 fix: snapshot + clear instead of while + pop(0).
        # list.pop(0) is O(n) per call (shifts all remaining elements), making
        # the full drain O(n²). Snapshot + clear is O(n) and preserves order.
        # Items added during processing are picked up on the next _finalize_pending() call.
        pending_tools = list(self._pending_tools)
        self._pending_tools.clear()
        for fn, opts in pending_tools:
            self._register_tool(fn, **opts)

        pending_prompts = list(self._pending_prompts)
        self._pending_prompts.clear()
        for fn, opts in pending_prompts:
            self._register_prompt(fn, **opts)

        pending_resources = list(self._pending_resources)
        self._pending_resources.clear()
        for fn, opts in pending_resources:
            self._register_resource(fn, **opts)

    # ── Middleware API ──────────────────────────────────────────────────

    def add_middleware(
        self,
        middleware: Middleware | type,
        name: str | None = None,
    ) -> None:
        """Register a global ProdMCP-level middleware (before/after hooks).

        Use this for cross-cutting concerns that run *inside* the request
        lifecycle of individual MCP tools, prompts, resources, and API
        routes — e.g. logging, timing, rate-limiting.

        For ASGI/HTTP-level middlewares such as CORS, GZip, or TrustedHost,
        use :meth:`add_asgi_middleware` instead.

        Args:
            middleware: A :class:`~prodmcp.middleware.Middleware` instance or class.
            name: Optional name for per-entity referencing.
        """
        self._middleware_manager.add(middleware, name=name)

    def add_asgi_middleware(self, cls: type, **kwargs: Any) -> None:
        """Register an ASGI-level (Starlette/FastAPI) middleware.

        These middlewares are applied directly to the underlying ``FastAPI``
        application during :meth:`run` (via :func:`~prodmcp.router.create_unified_app`)
        and to the app returned by :meth:`as_fastapi`.

        Use this for HTTP-transport–level concerns such as CORS, GZip,
        TrustedHost, session cookies, etc.

        Example::

            from fastapi.middleware.cors import CORSMiddleware

            app.add_asgi_middleware(
                CORSMiddleware,
                allow_origins=["*"],
                allow_methods=["*"],
                allow_headers=["*"],
            )

        Args:
            cls: Starlette/FastAPI middleware class.
            **kwargs: Arguments forwarded to the middleware constructor.
        """
        self._middleware_manager.add_asgi(cls, **kwargs)

    def add_exception_handler(
        self,
        exc_class_or_status_code: type | int,
        handler: Callable[..., Any],
    ) -> None:
        """Register a global HTTP exception handler.

        Handlers registered here are applied to the underlying ``FastAPI``
        application by both :func:`~prodmcp.router.create_unified_app` and
        :func:`~prodmcp.fastapi.create_fastapi_app`, ensuring they are not
        lost when a fresh FastAPI instance is built.

        This mirrors FastAPI's own ``app.add_exception_handler()`` API.

        Example::

            from fastapi import Request
            from fastapi.responses import JSONResponse

            async def value_error_handler(request: Request, exc: ValueError):
                return JSONResponse(status_code=400, content={"detail": str(exc)})

            app.add_exception_handler(ValueError, value_error_handler)

        Args:
            exc_class_or_status_code: Exception class or HTTP status code integer.
            handler: Async (or sync) callable ``(request, exc) -> Response``.
        """
        self._exception_handlers.append((exc_class_or_status_code, handler))

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
        # B3 fix: use explicit None-check instead of truthiness ('or').
        # 'output_schema or response_model' incorrectly falls through to
        # response_model when output_schema is any falsy-but-intentional value.
        # Also warn when both are provided so the silent discard is visible.
        import warnings as _w
        if output_schema is not None and response_model is not None:
            _w.warn(
                "Both output_schema and response_model were passed to @app.common(); "
                "output_schema takes precedence and response_model is ignored.",
                UserWarning,
                stacklevel=2,
            )
        effective_output = output_schema if output_schema is not None else response_model

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

        # Build the core handler (validation + security + middleware)
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

        # Bug 10 fix: inject HTTP request headers into __security_context__ for MCP tool calls.
        #
        # The security problem:
        # - For REST routes, router.py's _api_handler_secured builds __security_context__
        #   from the FastAPI Request object and passes it to the handler as a kwarg.
        # - For MCP tool calls (via streamable-HTTP MCP protocol), FastMCP invokes the
        #   handler with only the tool's input arguments — __security_context__ is NEVER
        #   injected, so _wrap_with_security → SecurityManager.check() → scheme.extract()
        #   sees an empty context dict and raises ProdMCPSecurityError every time.
        #
        # Fix: if the tool has security config, wrap the handler with a FastMCP-Context-
        # aware outer callable.  FastMCP automatically injects `ctx: fastmcp.Context` into
        # any tool handler that declares it; ctx.request_context.request.headers carries
        # the HTTP headers (including Authorization) from the MCP POST request.
        # We extract those headers and inject them as __security_context__ so that the
        # inner _wrap_with_security layer can authenticate the request normally.
        mcp_handler = wrapped
        if eff_security:
            import functools

            _inner = wrapped
            _sec_cfg = eff_security

            @functools.wraps(fn)
            async def _mcp_secured_wrapper(*args: Any, ctx: Any = None, **kwargs: Any) -> Any:  # noqa: ANN401
                """FastMCP-Context-aware security bridge.

                Extracts HTTP request headers from the FastMCP Context and
                builds __security_context__ for the inner secured handler.
                """
                sec_ctx: dict[str, Any] = {}
                if ctx is not None:
                    try:
                        request = ctx.request_context.request
                        sec_ctx = {
                            "headers": dict(request.headers),
                            "query_params": dict(request.query_params),
                        }
                    except Exception:
                        pass  # If no HTTP context (e.g. stdio), leave empty

                return await _inner(*args, __security_context__=sec_ctx, **kwargs)

            # Preserve the stripped signature so FastMCP doesn't see __security_context__
            # or ctx in the tool's JSON schema — only user-visible input params.
            try:
                import inspect as _inspect
                from fastmcp import Context as _FMCPContext  # type: ignore[import-untyped]

                # Add ctx parameter so FastMCP injects it automatically
                _orig_sig = _inspect.signature(wrapped)
                _ctx_param = _inspect.Parameter(
                    "ctx",
                    kind=_inspect.Parameter.KEYWORD_ONLY,
                    default=None,
                    annotation=_FMCPContext,
                )
                # Only append if not already there
                _existing_params = list(_orig_sig.parameters.values())
                if not any(p.name == "ctx" for p in _existing_params):
                    _new_sig = _orig_sig.replace(parameters=_existing_params + [_ctx_param])
                else:
                    _new_sig = _orig_sig

                _mcp_secured_wrapper.__signature__ = _new_sig  # type: ignore[attr-defined]

                # Bug: @functools.wraps(fn) copies fn.__annotations__ onto the wrapper.
                # FastMCP's ParsedFunction uses typing.get_type_hints() / TypeAdapter which
                # reads __annotations__ *independently* of __signature__. If the original fn
                # had user-defined types (e.g. ctx: AzureADTokenContext with a non-Pydantic
                # _auth: AzureADAuth field), Pydantic schema generation crashes with
                # PydanticSchemaGenerationError: "arbitrary_types_allowed".
                #
                # Fix: reset __annotations__ to exactly what the new signature declares.
                # This ensures TypeAdapter/get_type_hints only sees types FastMCP can handle
                # (fastmcp.Context + the stripped tool params — none of the user dep types).
                _mcp_secured_wrapper.__annotations__ = {  # type: ignore[attr-defined]
                    p.name: p.annotation
                    for p in _new_sig.parameters.values()
                    if p.annotation is not _inspect.Parameter.empty
                }

                # Also sever the __wrapped__ chain: functools.wraps sets __wrapped__ = fn,
                # and inspect.signature / Pydantic may follow it. Severing it forces both
                # to use __signature__ and __annotations__ set above.
                _mcp_secured_wrapper.__wrapped__ = None  # type: ignore[attr-defined]

            except Exception:
                pass  # If FastMCP Context unavailable, fall through gracefully

            _mcp_secured_wrapper.__security_config__ = getattr(wrapped, "__security_config__", _sec_cfg)  # type: ignore[attr-defined]
            mcp_handler = _mcp_secured_wrapper


        # Store metadata.
        # B2 fix: store the pre-built `wrapped` handler so create_fastapi_app()
        # (_add_tool_route) can reuse it directly instead of calling _build_handler
        # again on the same fn — which would double-wrap middleware and re-mutate
        # fn.__signature__ (compounding B1).
        self._registry["tools"][tool_name] = {
            "name": tool_name,
            "description": tool_desc.strip(),
            "input_schema": eff_input,
            "output_schema": eff_output,
            "security": getattr(mcp_handler, "__security_config__", eff_security or []),
            "middleware": eff_middleware or [],
            "tags": eff_tags,
            "handler": fn,
            "wrapped": wrapped,   # B2: REST bridge uses this (already has _api_handler_secured)
            "strict": is_strict,
        }

        # Register with FastMCP using the MCP-secured wrapper
        self.mcp.tool(
            name=tool_name,
            description=tool_desc.strip(),
        )(mcp_handler)


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

        # Apply validation + global ProdMCP middleware hooks.
        wrapped = self._build_handler(
            fn,
            entity_type="prompt",
            entity_name=prompt_name,
            input_schema=eff_input,
            output_schema=eff_output,
            security_config=None,      # prompts don't support per-entity security
            entity_middleware=None,    # prompts don't support per-entity middleware
            strict=False,              # prompts always use non-strict output
        )

        # D8 fix: store wrapped handler so _add_prompt_route can reuse it (mirrors
        # the B2 fix applied to tools). Previously only raw fn was stored;
        # _add_prompt_route called _build_handler() again, double-wrapping middleware
        # (LoggingMiddleware fired twice per bridge call).
        self._registry["prompts"][prompt_name] = {
            "name": prompt_name,
            "description": prompt_desc.strip(),
            "input_schema": eff_input,
            "output_schema": eff_output,
            "tags": eff_tags,
            "handler": fn,
            "wrapped": wrapped,   # D8/E2: reused by _add_prompt_route
        }

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

        # B12 fix: warn on duplicate URI registrations.
        # Two resources with the same URI co-exist under different names, but the
        # bridge matches only the first occurrence — the second is silently
        # unreachable via REST. Emit a warning so developers catch it early.
        for _existing_name, _existing_meta in self._registry["resources"].items():
            if _existing_meta["uri"] == resource_uri:
                import warnings as _w
                _w.warn(
                    f"Resource URI {resource_uri!r} is already registered under "
                    f"name {_existing_name!r}. The new registration "
                    f"(name={resource_name!r}) will be unreachable via the REST "
                    "bridge (first-match wins). Check for duplicate URI registrations.",
                    UserWarning,
                    stacklevel=3,
                )
                break

        self._registry["resources"][resource_name] = {
            "name": resource_name,
            "description": resource_desc.strip(),
            "uri": resource_uri,
            "output_schema": eff_output,
            "tags": eff_tags,
            "handler": fn,       # raw fn — for re-wrapping if needed
            # "wrapped" is added below after building the handler
        }

        # Apply validation + global ProdMCP middleware hooks.
        # Previously only create_validated_handler() was called here, bypassing
        # the middleware chain.  Resources now get the same hook coverage as tools.
        wrapped = self._build_handler(
            fn,
            entity_type="resource",
            entity_name=resource_name,
            input_schema=None,          # resources don't take input schemas
            output_schema=eff_output,
            security_config=None,       # resources don't support per-entity security
            entity_middleware=None,     # resources don't support per-entity middleware
            strict=False,               # resources always use non-strict output
        )

        # Store the wrapped handler so the REST bridge can call it directly
        # with all security/middleware baked in (see fastapi._add_resource_route).
        self._registry["resources"][resource_name]["wrapped"] = wrapped


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
            # D6 fix: warn on duplicate route registration (same as B12 for resources).
            if registry_key in self._registry["api"]:
                import warnings as _wr
                _wr.warn(
                    f"API route {method.upper()} {path!r} is already registered. "
                    "The new handler will overwrite the existing one.",
                    UserWarning,
                    stacklevel=4,
                )
            self._registry["api"][registry_key] = {
                "path": path,
                "method": method.upper(),
                "handler": fn,
                "response_model": response_model,
                "status_code": resolved_status,
                "tags": tags,
                # B7 fix: guard against whitespace-only docstrings.
                # '   '.strip().splitlines() → [] → [][0] → IndexError at registration.
                "summary": summary or (
                    fn.__doc__.strip().splitlines()[0].strip()
                    if fn.__doc__ and fn.__doc__.strip() else None
                ),
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
            param_default = param.default
            # Bug 3 fix: duck-type Depends detection so fastapi.Depends is treated
            # identically to prodmcp.Depends.  Both expose a `.dependency` callable.
            # A strict isinstance() check missed fastapi.Depends entirely, leaving
            # dependencies unresolved and security chains silently bypassed.
            is_depends = isinstance(param_default, Depends) or (
                param_default is not inspect.Parameter.empty
                and hasattr(param_default, "dependency")
                and callable(getattr(param_default, "dependency", None))
            )
            if is_depends:
                has_dependencies = True
                dep = param_default.dependency
                if isinstance(dep, SecurityScheme):
                    scheme_name = f"auto_{dep.scheme_type}_{id(dep)}"
                    self.add_security_scheme(scheme_name, dep)
                    scopes = getattr(dep, "scopes", [])
                    if hasattr(dep, "scopes_description"):
                        scopes = list(dep.scopes_description.keys())
                    # Bug 1 fix: only append if not already present.
                    if not any(scheme_name in req for req in security_config):
                        security_config.append({scheme_name: scopes})
            else:
                new_params.append(param)

        stripped_sig = sig.replace(parameters=new_params)  # will be rebuilt below

        # ── Resolve string annotations (from __future__ import annotations) ──────
        # If the user's module has `from __future__ import annotations` (PEP 563),
        # ALL annotations are stored as strings (e.g. 'ItemRequest', not the class).
        # `inspect.signature` returns those strings verbatim, so downstream checks
        # like `isinstance(ann, type) and issubclass(ann, BaseModel)` silently fail.
        # `typing.get_type_hints(fn)` resolves the strings in fn.__globals__ — which
        # contains the user's module namespace where the class is defined.
        import typing as _typing
        try:
            _resolved_hints = _typing.get_type_hints(fn)
        except Exception:
            _resolved_hints = {}

        # Rebuild sig parameters with resolved annotations.
        _resolved_params = []
        for _p in sig.parameters.values():
            _resolved_ann = _resolved_hints.get(_p.name, _p.annotation)
            if _resolved_ann != _p.annotation:
                _p = _p.replace(annotation=_resolved_ann)
            _resolved_params.append(_p)
        sig = sig.replace(parameters=_resolved_params)

        # Re-strip with resolved annotations so stripped_sig also has real types.
        new_params_resolved = []
        for _p in sig.parameters.values():
            _is_dep = isinstance(_p.default, Depends) or (
                _p.default is not inspect.Parameter.empty
                and hasattr(_p.default, "dependency")
                and callable(getattr(_p.default, "dependency", None))
            )
            if not _is_dep:
                new_params_resolved.append(_p)
        stripped_sig = sig.replace(parameters=new_params_resolved)

        if has_dependencies:
            # Pre-compute the annotation map for Bug 8 coercion (done once at registration).
            _annotation_map: dict[str, Any] = {
                pname: pparam.annotation
                for pname, pparam in sig.parameters.items()
                if pparam.annotation is not inspect.Parameter.empty
            }

            @functools.wraps(fn)
            async def dep_wrapper(*args: Any, **kwargs: Any) -> Any:
                context = kwargs.pop("__request_context__", {})
                kwargs.pop("__security_context__", None)

                # Bug 8 fix: coerce dict body values to their annotated Pydantic model.
                # router.py now passes the body as kwargs[param_name]=dict when it detects
                # a BaseModel-annotated parameter.  Coerce here so fn always receives the
                # correct type, regardless of whether input_schema was explicitly set.
                from pydantic import BaseModel as _PydanticBM
                for _kname, _kval in list(kwargs.items()):
                    _ann = _annotation_map.get(_kname)
                    if (
                        isinstance(_kval, dict)
                        and _ann is not None
                        and isinstance(_ann, type)
                        and issubclass(_ann, _PydanticBM)
                        and not isinstance(_kval, _ann)
                    ):
                        try:
                            kwargs[_kname] = _ann(**_kval)
                        except Exception:
                            pass  # leave as dict; validation layer will surface the error

                resolved = await resolve_dependencies(fn, context, overrides=kwargs)
                kwargs.update(resolved)

                if inspect.iscoroutinefunction(fn):
                    return await fn(*args, **kwargs)
                return fn(*args, **kwargs)

            dep_wrapper.__signature__ = stripped_sig
            # ── Clear __wrapped__ (set by functools.wraps) ──────────────────────
            # FastAPI follows __wrapped__ via get_typed_signature → typing.get_type_hints
            # and sees the *original* fn signature (with Depends params). FastAPI then
            # treats those params as query/body parameters → 422. We own the __signature__;
            # removing __wrapped__ prevents FastAPI from looking past it.
            dep_wrapper.__wrapped__ = None  # type: ignore[attr-defined]
            handler = dep_wrapper
        else:
            # B1 fix: do NOT assign stripped_sig to fn.__signature__ directly.
            # handler = fn followed by handler.__signature__ = ... mutates the
            # original function object. On stacked decorators (@app.tool + @app.get)
            # the second call to _build_handler sees already-stripped params —
            # Depends() detection breaks and fn is permanently corrupted.
            # Use a thin wrapper that carries the stripped signature instead.

            # Pre-compute annotation map for Bug 8 coercion (same logic as dep_wrapper path).
            _annotation_map_nd: dict[str, Any] = {
                pname: pparam.annotation
                for pname, pparam in sig.parameters.items()
                if pparam.annotation is not inspect.Parameter.empty
            }

            def _make_coercion_wrapper(wrapped_fn: Any, ann_map: dict[str, Any]) -> Any:
                """Return a thin wrapper that coerces dict body kwargs to BaseModel."""
                from pydantic import BaseModel as _PydanticBM

                if inspect.iscoroutinefunction(wrapped_fn):
                    @functools.wraps(wrapped_fn)
                    async def _sig_wrapper(*args: Any, **kwargs: Any) -> Any:  # type: ignore[misc]
                        for _kn, _kv in list(kwargs.items()):
                            _an = ann_map.get(_kn)
                            if (
                                isinstance(_kv, dict) and _an is not None
                                and isinstance(_an, type) and issubclass(_an, _PydanticBM)
                                and not isinstance(_kv, _an)
                            ):
                                try:
                                    kwargs[_kn] = _an(**_kv)
                                except Exception:
                                    pass
                        return await wrapped_fn(*args, **kwargs)
                else:
                    @functools.wraps(wrapped_fn)
                    def _sig_wrapper(*args: Any, **kwargs: Any) -> Any:  # type: ignore[misc]
                        for _kn, _kv in list(kwargs.items()):
                            _an = ann_map.get(_kn)
                            if (
                                isinstance(_kv, dict) and _an is not None
                                and isinstance(_an, type) and issubclass(_an, _PydanticBM)
                                and not isinstance(_kv, _an)
                            ):
                                try:
                                    kwargs[_kn] = _an(**_kv)
                                except Exception:
                                    pass
                        return wrapped_fn(*args, **kwargs)
                return _sig_wrapper

            _sig_wrapper = _make_coercion_wrapper(fn, _annotation_map_nd)
            _sig_wrapper.__signature__ = stripped_sig
            _sig_wrapper.__wrapped__ = None  # type: ignore[attr-defined]
            handler = _sig_wrapper

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
            # Bug P3-5 fix: auto-register shorthand security schemes into
            # _security_manager._schemes at registration time so that
            # generate_security_spec() (called during spec export) can remain
            # read-only — no more side-effectful scheme registration during spec gen.
            for req in security_config:
                if "type" in req:
                    auth_type = req.get("type", "").lower()
                    scopes = req.get("scopes", [])
                    if auth_type == "bearer":
                        if "bearerAuth" not in self._security_manager._schemes:
                            from .security.http import HTTPBearer
                            self.add_security_scheme("bearerAuth", HTTPBearer(scopes=scopes))
                        elif scopes:
                            # D9 fix: merge new scopes into the existing shared bearerAuth
                            # scheme so the OpenMCP spec advertises the union of all scopes.
                            # Without this, the first tool's scopes silently win and later
                            # tools' extra scopes are invisible in components.securitySchemes.
                            existing = self._security_manager._schemes["bearerAuth"]
                            if hasattr(existing, "scopes") and existing.scopes is not None:
                                merged = list(dict.fromkeys(list(existing.scopes) + list(scopes)))
                                existing.scopes = merged
                    elif auth_type == "apikey":
                        key_name = req.get("key_name", "X-API-Key")
                        location = req.get("in", "header")
                        scheme_name = f"apiKeyAuth_{location}_{key_name}"
                        if scheme_name not in self._security_manager._schemes:
                            from .security.api_key import APIKeyHeader, APIKeyQuery, APIKeyCookie
                            if location == "header":
                                self.add_security_scheme(scheme_name, APIKeyHeader(name=key_name))
                            elif location == "query":
                                self.add_security_scheme(scheme_name, APIKeyQuery(name=key_name))
                            elif location == "cookie":
                                self.add_security_scheme(scheme_name, APIKeyCookie(name=key_name))
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

        # D2 fix: pre-compute expensive values once at handler-build time, not
        # inside the per-request async function.  inspect.signature() constructs a
        # Signature object on every call; for functools.wraps-wrapped handlers the
        # CPython cache may not apply, burning CPU on every request.
        _has_dependencies = getattr(handler, "__has_dependencies__", False)
        _has_sec_ctx_param = "__security_context__" in inspect.signature(handler).parameters

        @functools.wraps(handler)
        async def secured(**kwargs: Any) -> Any:
            context = kwargs.pop("__security_context__", {})
            security_mgr.check(context, security_config)

            if _has_dependencies:
                kwargs["__request_context__"] = context

            if _has_sec_ctx_param:
                kwargs["__security_context__"] = context

            if inspect.iscoroutinefunction(handler):
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
            host: Bind address (default ``"0.0.0.0"``).
            port: Port number (default ``8000``).
            transport: One of ``"unified"`` (default), ``"stdio"``, ``"sse"``,
                ``"http"``, or ``"streamable-http"``.

                - ``"unified"``: Serves both REST API and MCP on one HTTP server.
                  REST routes at ``/``, MCP endpoint at ``{mcp_path}``.
                - ``"stdio"``: Pure MCP over stdin/stdout (local subprocess mode).
                - ``"sse"`` / ``"http"`` / ``"streamable-http"``: Pure FastMCP HTTP
                  server (no REST routes).  ASGI middlewares registered via
                  :meth:`add_asgi_middleware` (e.g. ``CORSMiddleware``) are
                  forwarded to FastMCP's HTTP server so they apply to all MCP
                  endpoints.
            **kwargs: Additional keyword arguments forwarded to the underlying
                transport. For the unified transport these are passed to
                ``uvicorn.run()`` (e.g. ``log_level``, ``reload``, ``workers``).
                For stdio/sse/http transports these are forwarded to FastMCP's
                runner. Note: ``uvicorn_config`` is NOT a valid kwarg — pass
                uvicorn options directly (``log_level="debug"``, etc.).
        """
        self._finalize_pending()

        if transport == "stdio":
            self.mcp.run(transport="stdio", **kwargs)

        elif transport in {"sse", "http", "streamable-http"}:
            # ── Inject ASGI middlewares into FastMCP's HTTP server ────────
            # FastMCP's run_http_async() natively accepts a `middleware`
            # parameter (list of starlette.middleware.Middleware).  Using this
            # path instead of self.mcp.run() lets us inject CORSMiddleware and
            # friends so they cover all MCP HTTP endpoints (/sse, /messages…).
            try:
                from starlette.middleware import Middleware as StarletteMiddleware
            except ImportError:
                logger.warning(
                    "starlette not installed; ASGI middlewares cannot be applied "
                    "to the %r FastMCP transport.  Install with "
                    "`pip install prodmcp[rest]`.",
                    transport,
                )
                self.mcp.run(transport=transport, host=host, port=port, **kwargs)
                return

            # Convert ProdMCP ASGIMiddlewareConfig → starlette Middleware objects
            fastmcp_middlewares = [
                StarletteMiddleware(mw_cfg.cls, **mw_cfg.kwargs)
                for mw_cfg in self._middleware_manager.asgi_middlewares
            ]
            if fastmcp_middlewares:
                logger.debug(
                    "Forwarding %d ASGI middleware(s) to FastMCP %r transport",
                    len(fastmcp_middlewares),
                    transport,
                )

            import anyio
            from functools import partial

            anyio.run(
                partial(
                    self.mcp.run_http_async,
                    transport=transport,
                    host=host,
                    port=port,
                    middleware=fastmcp_middlewares or None,
                    **kwargs,
                )
            )

        else:
            # Unified mode: REST + MCP on same server
            from .router import create_unified_app
            unified = create_unified_app(self)
            try:
                import uvicorn
            except ImportError:
                raise ImportError(
                    "uvicorn is required for the unified server. "
                    "Install it with `pip install prodmcp[rest]`."
                )
            uvicorn.run(unified, host=host, port=port, **kwargs)

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
