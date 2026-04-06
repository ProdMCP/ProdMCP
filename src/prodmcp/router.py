"""Unified ASGI application builder for ProdMCP.

Creates a single Starlette/ASGI application that serves both:
- REST API routes (from @app.get, @app.post, etc.)
- MCP SSE endpoint (from @app.tool, @app.prompt, @app.resource)
"""

from __future__ import annotations

import inspect
import logging
from typing import TYPE_CHECKING, Any

# Bug 8 fix: Request and HTTPException must be module-level imports.
# `from __future__ import annotations` turns all annotations into strings.
# `_api_handler_secured(request: Request)` stores 'Request' as a string.
# FastAPI calls get_type_hints(_api_handler_secured) which looks up 'Request'
# in _api_handler_secured.__globals__ (the module namespace). If Request is
# only imported locally inside _add_api_route, it is NOT in __globals__, so
# get_type_hints() fails to resolve the type and FastAPI treats `request` as
# an unresolved parameter → query parameter → 422 on every request.
try:
    from fastapi import HTTPException, Request  # noqa: E402
except ImportError:  # [rest] not installed
    HTTPException = None  # type: ignore[assignment,misc]
    Request = None  # type: ignore[assignment,misc]

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
        from fastapi import FastAPI, Request, Depends as FastAPIDepends, HTTPException  # noqa: F401
        from starlette.routing import Mount  # noqa: F401
        from pydantic import BaseModel, create_model  # noqa: F401
    except ImportError as exc:
        raise ImportError(
            "FastAPI and Starlette are required for the unified server. "
            "Install them with `pip install prodmcp[rest]`."
        ) from exc

    # ── Finalize pending decorator registrations ──────────────────────
    # create_unified_app() is public — users may call it directly without
    # going through app.run(), which would normally call _finalize_pending().
    # Calling it here is idempotent (drain pattern) and ensures all
    # @app.tool / @app.prompt / @app.resource decorators are processed.
    app._finalize_pending()

    # ── Build the FastAPI sub-app for REST routes ──────────────────────

    fastapi_app = FastAPI(
        title=app.name,
        version=app.version,
        description=app.description,
    )

    # ── Apply ASGI-level middlewares (e.g. CORSMiddleware) ─────────────
    # These are registered via app.add_asgi_middleware() and must be
    # applied here so they participate in the full Starlette ASGI pipeline.
    # Middlewares are applied in *reverse* registration order so that the
    # first-registered middleware is outermost (executed first on requests).
    for mw_cfg in reversed(app._middleware_manager.asgi_middlewares):
        fastapi_app.add_middleware(mw_cfg.cls, **mw_cfg.kwargs)
        logger.debug(
            "Applied ASGI middleware %s to FastAPI app", mw_cfg.cls.__name__
        )

    # ── Apply global exception handlers ────────────────────────────────
    # Registered via app.add_exception_handler() — applied here so custom
    # error handling survives the fresh FastAPI instantiation.
    for exc_cls, handler in app._exception_handlers:
        fastapi_app.add_exception_handler(exc_cls, handler)
        logger.debug("Applied exception handler for %s", exc_cls)

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
            # ── Wrap the MCP sub-app with ASGI middlewares ────────────────
            # IMPORTANT: Starlette's mount() creates an isolated ASGI scope.
            # Middleware applied to the parent FastAPI app does NOT reach the
            # mounted sub-app.  We therefore manually wrap mcp_asgi with the
            # same middleware stack so that CORSMiddleware (and others) also
            # intercept requests to /mcp/sse, /mcp/messages, etc.
            #
            # Middlewares must be applied in *reverse* registration order so
            # the first-registered ends up as the outermost layer.
            asgi_mws = app._middleware_manager.asgi_middlewares
            if asgi_mws:
                for mw_cfg in reversed(asgi_mws):
                    try:
                        mcp_asgi = mw_cfg.cls(app=mcp_asgi, **mw_cfg.kwargs)
                        logger.debug(
                            "Wrapped MCP sub-app with ASGI middleware %s",
                            mw_cfg.cls.__name__,
                        )
                    except Exception as wrap_err:
                        logger.warning(
                            "Could not wrap MCP sub-app with %s: %s",
                            mw_cfg.cls.__name__,
                            wrap_err,
                        )

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
    # Request and HTTPException are imported at module level (Bug 8 fix).
    # ProdMCPSecurityError/ProdMCPValidationError are local to avoid circular imports.
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

    # Bug 4 fix: resolve __prodmcp_common__ at route-build time (create_unified_app).
    # Decorators execute bottom-up, so @app.common() runs and sets __prodmcp_common__
    # BEFORE @app.get/@app.post writes the registry entry. The registry therefore
    # always contains security=None/middleware=None for @app.common() routes.
    # By reading fn.__prodmcp_common__ here (lazily, not at decoration time) we
    # capture the final merged config — identical to how _finalize_pending() does
    # it for MCP tools.  Explicit per-route values still take precedence.
    common_cfg = getattr(handler_fn, "__prodmcp_common__", {})

    security_config = meta.get("security") or common_cfg.get("security")
    middleware_config = meta.get("middleware") or common_cfg.get("middleware")
    input_schema = meta.get("input_schema") or common_cfg.get("input_schema")

    if security_config or middleware_config or input_schema:
        # Build a ProdMCP-wrapped handler
        entity_name = operation_id or handler_fn.__name__
        wrapped = app._build_handler(
            handler_fn,
            entity_type="api",
            entity_name=entity_name,
            input_schema=input_schema,
            # Gap 3 fix: do NOT pass output_schema=response_model.
            # _build_handler's output validation calls model_dump() on the
            # result and returns a plain dict; FastAPI then tries to validate
            # that dict against response_model again — double-serialization.
            # This breaks alias field names and custom serializers.
            # FastAPI's response_model handling is the correct place for REST
            # output validation; ProdMCP handles input + security + middleware.
            output_schema=None,
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

            # C5 fix: guard against JSON array / scalar bodies.
            # `{**request.path_params, **body}` raises TypeError when body is a list
            # (e.g. client sends [1,2,3]). Return 422 instead of an unhandled 500.
            if not isinstance(body, dict):
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"Request body must be a JSON object ({{}}), "
                        f"not {type(body).__name__}."
                    ),
                )

            # Bug 8 fix: detect Pydantic body parameters in the wrapped handler's
            # signature and pass the body as a model INSTANCE keyed to the correct
            # parameter name, instead of always doing {**body} (flat key expansion).
            #
            # Problem: a handler like `chat(request: ChatRequest)` expects
            #   wrapped(request=ChatRequest(message="hello"))
            # but the old code called:
            #   wrapped(message="hello")  ← wrong param name → TypeError / 422
            #
            # This also fixes the reserved-name collision: the outer closure uses
            # `request` for the FastAPI Request object; a user param also named
            # `request` would overwrite it in the flat expansion.
            #
            # Algorithm:
            #   For each parameter in the inner handler's stripped signature (excluding
            #   meta injections and path params), if its annotation is a Pydantic
            #   BaseModel subclass, fold the entire body dict into one model instance
            #   keyed by that param name.  Otherwise keep the flat-expansion behaviour
            #   so simple scalar/dict handlers continue to work unchanged.
            try:
                from pydantic import BaseModel as _BaseModel
                _inner_sig = inspect.signature(wrapped)
                _body_key: str | None = None
                _body_type: type | None = None
                for _pname, _pparam in _inner_sig.parameters.items():
                    if _pname.startswith("__"):  # skip meta injections
                        continue
                    if _pname in request.path_params:  # already in path
                        continue
                    _ann = _pparam.annotation
                    if (
                        _ann is not inspect.Parameter.empty
                        and isinstance(_ann, type)
                        and issubclass(_ann, _BaseModel)
                    ):
                        _body_key = _pname
                        _body_type = _ann
                        break  # single body model expected
            except Exception:
                _body_key = None
                _body_type = None

            if _body_key is not None and _body_type is not None:
                # Build kwargs with the body folded into one model-valued param.
                # Path params are separate (they were already parsed by FastAPI/Starlette).
                kwargs = dict(request.path_params)   # path params win
                kwargs[_body_key] = body             # body dict; validation layer handles it
            else:
                # C6 fix: path parameters MUST win over body keys.
                # The previous order ({**request.path_params, **body}) let body keys
                # silently overwrite URL path parameters — a client could inject
                # arbitrary values for path params like 'item_id' via the JSON body,
                # bypassing route-level access control that depends on path params.
                kwargs = {**body, **request.path_params}  # path params take precedence

            # Bug D fix: only inject __security_context__ when security is
            # actually configured.  Injecting it unconditionally causes
            # TypeError on handlers that don't accept **kwargs and have no
            # security but do have input_schema or middleware_config.
            if security_config:
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

    # Gap 3 fix: if response_model not set explicitly on the route, fall back
    # to output_schema from @common().  This ensures @common(output_schema=M)
    # propagates to the OpenAPI response schema on REST routes.
    if response_model is None:
        common_cfg = getattr(handler_fn, "__prodmcp_common__", None)
        if common_cfg:
            response_model = common_cfg.get("output_schema") or common_cfg.get("response_model")

    # Gap 1 fix: response_description was stored in registry but never
    # forwarded to FastAPI — the value was silently discarded.
    response_description = meta.get("response_description")

    # Build route kwargs — use `is not None` guards (not truthiness) so that
    # intentionally falsy values like tags=[], deprecated=False, summary=""
    # are correctly forwarded to FastAPI instead of being silently dropped.
    route_kwargs: dict[str, Any] = {
        "methods": [method],
        "status_code": status_code,
        "include_in_schema": include_in_schema,
        "deprecated": deprecated,  # always forward; False is a valid explicit value
    }
    if tags is not None:
        route_kwargs["tags"] = tags
    if summary is not None:
        route_kwargs["summary"] = summary
    if description is not None:
        route_kwargs["description"] = description
    if operation_id is not None:
        route_kwargs["operation_id"] = operation_id
    if response_model is not None:
        route_kwargs["response_model"] = response_model
    if response_class is not None:
        route_kwargs["response_class"] = response_class
    if responses is not None:
        route_kwargs["responses"] = responses
    if response_description is not None:
        route_kwargs["response_description"] = response_description

    fastapi_app.add_api_route(path, endpoint, **route_kwargs)
