"""Unified ASGI application builder for ProdMCP.

Creates a single Starlette/ASGI application that serves both:
- REST API routes (from @app.get, @app.post, etc.)
- MCP SSE endpoint (from @app.tool, @app.prompt, @app.resource)
"""

from __future__ import annotations

import inspect
import logging
from typing import TYPE_CHECKING, Any, Callable, Type

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from .app import ProdMCP


def create_unified_app(app: "ProdMCP") -> Any:
    """Create a unified ASGI application from a ProdMCP instance.

    - REST routes are served via FastAPI at the root.
    - MCP SSE is mounted at app.mcp_path (default "/mcp").

    Args:
        app: The ProdMCP application instance.

    Returns:
        A Starlette/ASGI application suitable for uvicorn.run().
    """
    try:
        from fastapi import FastAPI, Request, Depends as FastAPIDepends, HTTPException
        from starlette.routing import Mount
        from pydantic import BaseModel, create_model
    except ImportError as exc:
        raise ImportError(
            "FastAPI and Starlette are required for the unified server. "
            "Install them with `pip install prodmcp[rest]`."
        ) from exc

    # ── Build the FastAPI sub-app for REST routes ──────────────────────

    fastapi_app = FastAPI(
        title=app.name,
        version=app.version,
        description=app.description,
    )

    # Register explicit API routes from @app.get(), @app.post(), etc.
    for key, meta in app._registry.get("api", {}).items():
        _add_api_route(fastapi_app, app, meta)

    # ── Mount the MCP SSE app ─────────────────────────────────────────

    try:
        # FastMCP exposes an ASGI-compatible app via .sse_app() or similar
        mcp_instance = app.mcp
        if hasattr(mcp_instance, "sse_app"):
            mcp_asgi = mcp_instance.sse_app()
        elif hasattr(mcp_instance, "http_app"):
            mcp_asgi = mcp_instance.http_app()
        else:
            # Fallback: try to get the streamable-http ASGI app
            mcp_asgi = None
            logger.warning(
                "FastMCP instance does not expose sse_app() or http_app(). "
                "MCP endpoint will not be available."
            )

        if mcp_asgi:
            fastapi_app.mount(app.mcp_path, mcp_asgi)
            logger.info("MCP SSE mounted at %s", app.mcp_path)
    except Exception as e:
        logger.warning("Failed to mount MCP SSE app: %s", e)

    return fastapi_app


def _add_api_route(
    fastapi_app: Any,
    app: "ProdMCP",
    meta: dict[str, Any],
) -> None:
    """Add a single API route to the FastAPI application."""
    from fastapi import Request, HTTPException
    from .exceptions import ProdMCPSecurityError, ProdMCPValidationError

    handler_fn = meta["handler"]
    path = meta["path"]
    method = meta["method"]
    response_model = meta.get("response_model")
    status_code = meta.get("status_code", 200)
    tags = meta.get("tags")
    summary = meta.get("summary")
    description = meta.get("description")
    deprecated = meta.get("deprecated", False)
    operation_id = meta.get("operation_id")
    include_in_schema = meta.get("include_in_schema", True)
    response_class = meta.get("response_class")
    responses = meta.get("responses")

    # Check if we need to apply ProdMCP security/middleware wrapping
    security_config = meta.get("security")
    middleware_config = meta.get("middleware")
    input_schema = meta.get("input_schema")

    if security_config or middleware_config or input_schema:
        # Build a ProdMCP-wrapped handler
        entity_name = operation_id or handler_fn.__name__
        wrapped = app._build_handler(
            handler_fn,
            entity_type="api",
            entity_name=entity_name,
            input_schema=input_schema,
            output_schema=response_model,
            security_config=security_config,
            entity_middleware=middleware_config,
            strict=app.strict_output,
        )

        is_async = inspect.iscoroutinefunction(wrapped)

        async def _api_handler_secured(request: Request) -> Any:
            # Build security context from HTTP request
            sec_ctx = {
                "headers": dict(request.headers),
                "query_params": dict(request.query_params),
                "cookies": dict(request.cookies),
            }
            try:
                body = await request.json() if request.headers.get("content-type") == "application/json" else {}
            except Exception:
                body = {}

            # Merge path params and body
            kwargs = {**request.path_params, **body}
            kwargs["__security_context__"] = sec_ctx

            try:
                if is_async:
                    return await wrapped(**kwargs)
                return wrapped(**kwargs)
            except ProdMCPSecurityError as e:
                raise HTTPException(status_code=403, detail=str(e)) from e
            except ProdMCPValidationError as e:
                raise HTTPException(
                    status_code=422, detail={"errors": e.errors, "message": str(e)}
                ) from e

        endpoint = _api_handler_secured
    else:
        # Pass through directly — pure FastAPI behavior
        endpoint = handler_fn

    # Build route kwargs
    route_kwargs: dict[str, Any] = {
        "methods": [method],
        "status_code": status_code,
    }
    if tags:
        route_kwargs["tags"] = tags
    if summary:
        route_kwargs["summary"] = summary
    if description:
        route_kwargs["description"] = description
    if deprecated:
        route_kwargs["deprecated"] = deprecated
    if operation_id:
        route_kwargs["operation_id"] = operation_id
    if response_model:
        route_kwargs["response_model"] = response_model
    if response_class:
        route_kwargs["response_class"] = response_class
    if responses:
        route_kwargs["responses"] = responses
    route_kwargs["include_in_schema"] = include_in_schema

    fastapi_app.add_api_route(path, endpoint, **route_kwargs)
