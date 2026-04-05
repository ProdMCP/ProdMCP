"""FastAPI bridge for ProdMCP.

Auto-generates a FastAPI application from a registered ProdMCP instance.
"""

from __future__ import annotations

import inspect
import logging
import re
from typing import TYPE_CHECKING, Any, Callable, Type

try:
    from fastapi import Depends, FastAPI, HTTPException, Request  # noqa: F401
    from pydantic import BaseModel, create_model  # noqa: F401
except ModuleNotFoundError as exc:
    # E1 fix: narrow from ImportError to ModuleNotFoundError.
    # ImportError is too broad — it is also raised for sub-import failures inside
    # an installed package (broken plugins, missing pydantic extras, etc.).
    # ModuleNotFoundError fires only when the top-level package is absent.
    raise ImportError(
        "FastAPI is required for the REST bridge. "
        "Install it with `pip install prodmcp[rest]`."
    ) from exc

from .exceptions import ProdMCPSecurityError, ProdMCPValidationError

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from .app import ProdMCP


def create_fastapi_app(app: "ProdMCP", title: str | None = None) -> FastAPI:
    """Create a FastAPI application from a ProdMCP instance."""
    app_title = title or app.name or "ProdMCP Server"
    fastapi_app = FastAPI(
        title=app_title, version=app.version, description=app.description
    )

    # ── Apply ASGI-level middlewares (e.g. CORSMiddleware) ─────────────
    # Mirrors create_unified_app() — same registered configs must be applied
    # here so that app.as_fastapi() / app.test_mcp_as_fastapi() also get
    # CORS, GZip, TrustedHost, etc. without the user having to re-apply them.
    for mw_cfg in reversed(app._middleware_manager.asgi_middlewares):
        fastapi_app.add_middleware(mw_cfg.cls, **mw_cfg.kwargs)
        logger.debug(
            "Applied ASGI middleware %s to FastAPI app (bridge)", mw_cfg.cls.__name__
        )

    # ── Apply global exception handlers ────────────────────────────────
    for exc_cls, handler in app._exception_handlers:
        fastapi_app.add_exception_handler(exc_cls, handler)
        logger.debug("Applied exception handler for %s (bridge)", exc_cls)

    def get_security_context(request: Request) -> dict[str, Any]:
        """Extract HTTP context (headers/params/cookies) into a Dict for ProdMCP Security."""
        return {
            "headers": dict(request.headers),
            "query_params": dict(request.query_params),
            "cookies": dict(request.cookies),
        }

    def _ensure_pydantic(
        name: str, schema: Type[BaseModel] | dict[str, Any] | None
    ) -> Type[BaseModel] | None:
        if schema is None:
            return None
        if isinstance(schema, type) and issubclass(schema, BaseModel):
            return schema
        if isinstance(schema, dict) and "properties" in schema:
            fields: dict[str, Any] = {}
            for k, v in schema.get("properties", {}).items():
                is_req = k in schema.get("required", [])
                fields[k] = (Any, ... if is_req else None)
            m = create_model(name, **fields)
            return m
        return None

    # Map Tools
    for name, meta in app._registry["tools"].items():
        _add_tool_route(
            fastapi_app, app, name, meta, get_security_context, _ensure_pydantic
        )

    # Map Prompts — pass `app` so _add_prompt_route can use _build_handler
    for name, meta in app._registry["prompts"].items():
        _add_prompt_route(
            fastapi_app, app, name, meta, _ensure_pydantic
        )

    # Single wild-card route for URL-encoded Resources
    _add_resource_route(fastapi_app, app, get_security_context)

    return fastapi_app


def _add_tool_route(
    fastapi_app: FastAPI,
    app: "ProdMCP",
    name: str,
    meta: dict[str, Any],
    get_security_context: Callable,
    _ensure_pydantic: Callable,
) -> None:
    handler_fn = meta["handler"]
    in_schema = meta["input_schema"]
    out_schema = meta["output_schema"]

    model_class = _ensure_pydantic(f"Tool{name.capitalize()}Input", in_schema)

    # B2 fix: reuse the pre-built wrapped handler stored during _register_tool.
    # Calling _build_handler() again on the same fn would:
    #   1. Double-wrap the middleware chain (LoggingMiddleware fires twice).
    #   2. Compound B1 by re-stripping an already-stripped fn.__signature__.
    # meta["wrapped"] is guaranteed to exist for all tools registered via
    # _register_tool(); the fallback handles any future code paths that bypass it.
    if "wrapped" in meta:
        wrapped_handler = meta["wrapped"]
    else:
        wrapped_handler = app._build_handler(
            handler_fn,
            entity_type="tool",
            entity_name=name,
            input_schema=in_schema,
            output_schema=out_schema,
            security_config=meta["security"],
            entity_middleware=meta["middleware"],
            strict=meta["strict"],
        )

    is_async = inspect.iscoroutinefunction(wrapped_handler)

    async def _execute_wrapped(kwargs: dict[str, Any]) -> Any:
        # P2-10 fix: only catch ProdMCP-specific exceptions here.
        # Non-ProdMCP exceptions (ValueError, TypeError, etc.) propagate
        # naturally to FastAPI's exception handler chain so that handlers
        # registered via app.add_exception_handler() can intercept them.
        # Previously a broad `except Exception` swallowed everything as 500,
        # making custom exception handlers silently ineffective for tool errors.
        try:
            if is_async:
                return await wrapped_handler(**kwargs)
            return wrapped_handler(**kwargs)
        except ProdMCPSecurityError as e:
            raise HTTPException(status_code=403, detail=str(e)) from e
        except ProdMCPValidationError as e:
            raise HTTPException(
                status_code=422, detail={"errors": e.errors, "message": str(e)}
            ) from e
        except HTTPException:
            raise

    if model_class:
        async def typed_route_handler(
            request: Request,
            sec_ctx: dict[str, Any] = Depends(get_security_context),
            payload: Any = None,
        ) -> Any:
            kwargs = payload.model_dump()
            if meta.get("security"):
                kwargs["__security_context__"] = sec_ctx
            return await _execute_wrapped(kwargs)

        sig = inspect.signature(typed_route_handler)
        params = list(sig.parameters.values())
        params[-1] = params[-1].replace(annotation=model_class)
        typed_route_handler.__signature__ = sig.replace(parameters=params)

        handler_to_use = typed_route_handler
    else:
        async def dict_route_handler(
            request: Request,
            sec_ctx: dict[str, Any] = Depends(get_security_context),
        ) -> Any:
            try:
                if request.headers.get("content-type") == "application/json":
                    body = await request.json()
                else:
                    body = {}
            except Exception:
                body = {}
            # B8 fix: dict(body) raises TypeError when body is a JSON array or
            # scalar (e.g. [1,2,3] or 42). Guard here and return a 422 instead
            # of letting an unhandled TypeError propagate as a 500.
            if not isinstance(body, dict):
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"Tool input body must be a JSON object ({{}}), "
                        f"not {type(body).__name__}."
                    ),
                )
            kwargs = body
            if meta.get("security"):
                kwargs["__security_context__"] = sec_ctx
            return await _execute_wrapped(kwargs)

        handler_to_use = dict_route_handler

    fastapi_app.add_api_route(
        f"/tools/{name}",
        handler_to_use,
        methods=["POST"],
        summary=f"Execute tool: {name}",
        description=meta["description"],
    )


def _add_prompt_route(
    fastapi_app: FastAPI,
    app: "ProdMCP",
    name: str,
    meta: dict[str, Any],
    _ensure_pydantic: Callable,
) -> None:
    handler_fn = meta["handler"]
    in_schema = meta["input_schema"]
    out_schema = meta["output_schema"]

    model_class = _ensure_pydantic(f"Prompt{name.capitalize()}Input", in_schema)

    # D8/E2 fix: reuse the pre-built wrapped handler stored during _register_prompt.
    # Previously _build_handler() was always called here, causing double middleware
    # wrapping in as_fastapi() / test_mcp_as_fastapi() — LoggingMiddleware fired twice.
    # _register_prompt now stores "wrapped" in the registry (mirrors the B2 tool fix).
    if "wrapped" in meta:
        wrapped_handler = meta["wrapped"]
    else:
        # Fallback for any future code path that bypasses _register_prompt.
        wrapped_handler = app._build_handler(
            handler_fn,
            entity_type="prompt",
            entity_name=name,
            input_schema=in_schema,
            output_schema=out_schema,
            security_config=None,
            entity_middleware=None,
            strict=False,
        )
    is_async = inspect.iscoroutinefunction(wrapped_handler)

    async def _execute_wrapped(kwargs: dict[str, Any]) -> Any:
        # P2-10 fix: same typed-except pattern as _add_tool_route.
        try:
            if is_async:
                return await wrapped_handler(**kwargs)
            return wrapped_handler(**kwargs)
        except ProdMCPSecurityError as e:
            raise HTTPException(status_code=403, detail=str(e)) from e
        except ProdMCPValidationError as e:
            raise HTTPException(
                status_code=422, detail={"errors": e.errors, "message": str(e)}
            ) from e
        except HTTPException:
            raise

    if model_class:
        async def typed_route_handler(
            payload: Any = None,
        ) -> Any:
            kwargs = payload.model_dump()
            return await _execute_wrapped(kwargs)

        sig = inspect.signature(typed_route_handler)
        params = list(sig.parameters.values())
        params[0] = params[0].replace(annotation=model_class)
        typed_route_handler.__signature__ = sig.replace(parameters=params)

        handler_to_use = typed_route_handler
    else:
        async def dict_route_handler(
            request: Request,
        ) -> Any:
            try:
                if request.headers.get("content-type") == "application/json":
                    body = await request.json()
                else:
                    body = {}
            except Exception:
                body = {}
            # E3 fix: guard against JSON array / scalar bodies (same as B8 for tool routes).
            # `dict(body)` / `**body` raises TypeError when body is a list or scalar.
            if not isinstance(body, dict):
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"Request body must be a JSON object ({{}}), "
                        f"not {type(body).__name__}."
                    ),
                )
            kwargs = body
            return await _execute_wrapped(kwargs)

        handler_to_use = dict_route_handler

    fastapi_app.add_api_route(
        f"/prompts/{name}",
        handler_to_use,
        methods=["POST"],
        summary=f"Execute prompt: {name}",
        description=meta["description"],
    )


def _match_uri_template(template: str, uri: str) -> dict[str, str] | None:
    """Match a URI against an RFC 6570 {variable} template.

    Returns a dict of captured variables on match, or ``None`` if no match.
    Supports single-segment (non-slash) captures matching ``{var}`` syntax.

    Examples::

        _match_uri_template("data://{id}", "data://42")  # {"id": "42"}
        _match_uri_template("resource://{a}/{b}", "resource://x/y")  # {"a": "x", "b": "y"}
        _match_uri_template("static://item", "static://item")  # {} (no vars)
        _match_uri_template("data://{id}", "other://42")  # None
    """
    # Escape everything, then un-escape the {var} placeholders
    escaped = re.escape(template)
    # re.escape turns {var} → \{var\}; convert back to named capture group
    pattern = re.sub(r"\\\{(\w+)\\\}", r"(?P<\1>[^/]+)", escaped)
    m = re.fullmatch(pattern, uri)
    return m.groupdict() if m else None


def _add_resource_route(
    fastapi_app: FastAPI,
    app: "ProdMCP",
    get_security_context: Callable,
) -> None:
    async def resource_route_handler(
        mcp_uri: str,
        request: Request,
        sec_ctx: dict[str, Any] = Depends(get_security_context),
    ) -> Any:
        from fastapi import HTTPException

        # ── Bug B + Bug 6 fix: use ProdMCP registry for security + URI params ──
        # The old code called app.mcp.read_resource() directly (security bypass)
        # and always called wrapped() with no args (TypeError for parameterized
        # resources like @app.resource(uri="data://{item_id}")).
        #
        # Strategy:
        # 1. Try exact URI match first (static resources).
        # 2. Try URI template match (parameterized resources) — extract vars
        #    and pass them as kwargs to the wrapped handler.
        # 3. Fall back to FastMCP's native read with a security warning.
        # E4 fix: removed outer try/except that silently swallowed all Python
        # errors from the registry lookup and handler call as wrong-status 404s.
        # The inner try/except (around the handler call) already maps:
        #   ProdMCPSecurityError  → 403
        #   ProdMCPValidationError → 422
        #   HTTPException         → re-raised
        #   other                 → 500
        # Only the FastMCP fallback (Step 3) warrants a 404.

        # Step 1 & 2: search registry for exact or template match
        match_meta: dict | None = None
        match_kwargs: dict[str, str] = {}

        for rmeta in app._registry["resources"].values():
            registered_uri = rmeta["uri"]
            if registered_uri == mcp_uri:
                match_meta = rmeta
                match_kwargs = {}
                break
            else:
                captured = _match_uri_template(registered_uri, mcp_uri)
                if captured is not None:
                    match_meta = rmeta
                    match_kwargs = captured
                    break

        if match_meta is not None:
            wrapped = match_meta.get("wrapped")
            if wrapped is None:
                wrapped = match_meta["handler"]
            try:
                if inspect.iscoroutinefunction(wrapped):
                    result = await wrapped(**match_kwargs)
                else:
                    result = wrapped(**match_kwargs)
            except Exception as handler_exc:
                from .exceptions import ProdMCPSecurityError, ProdMCPValidationError
                if isinstance(handler_exc, ProdMCPSecurityError):
                    raise HTTPException(status_code=403, detail=str(handler_exc)) from handler_exc
                if isinstance(handler_exc, ProdMCPValidationError):
                    raise HTTPException(
                        status_code=422,
                        detail={"errors": handler_exc.errors, "message": str(handler_exc)},
                    ) from handler_exc
                if isinstance(handler_exc, HTTPException):
                    raise
                raise HTTPException(status_code=500, detail=str(handler_exc)) from handler_exc
            return {"content": result}

        # Step 3: No ProdMCP registry match — fall back to FastMCP.
        # WARNING: this path does NOT apply ProdMCP security or middleware.
        logger.warning(
            "Resource %r not found in ProdMCP registry (neither exact nor "
            "template match); falling back to FastMCP read — ProdMCP "
            "security and middleware will NOT apply.",
            mcp_uri,
        )
        # E4 fix: only the FastMCP fallback call produces a 404.
        try:
            content = await app.mcp.read_resource(mcp_uri)
            return {"content": content}
        except Exception as e:
            raise HTTPException(status_code=404, detail=str(e)) from e

    fastapi_app.add_api_route(
        "/resources/{mcp_uri:path}",
        resource_route_handler,
        methods=["GET"],
        summary="Read any Resource by URI template",
    )
