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

from pydantic import ConfigDict, Field

from .exceptions import ProdMCPSecurityError, ProdMCPValidationError

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from .app import ProdMCP


# ── Schema hardening at the MODEL level (not post-patch) ──────────────────────


def _harden_anyof_in_schema(schema: dict[str, Any]) -> None:
    """Pydantic ``json_schema_extra`` callback — hardens anyOf/oneOf at generation time.

    Walks the generated JSON Schema and adds ``additionalProperties: false``
    to primitive ``anyOf``/``oneOf`` constructs (e.g. ``Optional[str]``).
    This runs during ``model_json_schema()`` — not as a post-patch.
    """
    for prop in schema.get("properties", {}).values():
        if not isinstance(prop, dict):
            continue
        _apply_anyof_hardening(prop)


def _apply_anyof_hardening(node: dict[str, Any]) -> None:
    """Recursively add additionalProperties:false to primitive anyOf/oneOf."""
    for key in ("anyOf", "oneOf"):
        subs = node.get(key)
        if not isinstance(subs, list):
            continue
        all_primitive = all(
            isinstance(s, dict) and "properties" not in s for s in subs
        )
        if all_primitive and "additionalProperties" not in node:
            node["additionalProperties"] = False
    # Recurse into nested properties
    for prop in node.get("properties", {}).values():
        if isinstance(prop, dict):
            _apply_anyof_hardening(prop)
    items = node.get("items")
    if isinstance(items, dict):
        _apply_anyof_hardening(items)


def _ensure_strict_model(model: type) -> type:
    """Ensure a Pydantic model has ``extra='forbid'`` and anyOf hardening.

    If the model already satisfies these constraints, returns it unchanged.
    Otherwise, creates a strict subclass with the same name so the generated
    OpenAPI schema title remains identical.  This happens at registration
    time — not as a post-patch of the OpenAPI dict.
    """
    if not isinstance(model, type) or not issubclass(model, BaseModel):
        return model
    config = getattr(model, "model_config", {})
    needs_extra = config.get("extra") != "forbid"
    needs_anyof = config.get("json_schema_extra") is None
    if not needs_extra and not needs_anyof:
        return model
    new_config = {**config}
    if needs_extra:
        new_config["extra"] = "forbid"
    if needs_anyof:
        new_config["json_schema_extra"] = _harden_anyof_in_schema
    return type(
        model.__name__,
        (model,),
        {"model_config": ConfigDict(**new_config), "__module__": model.__module__},
    )


# ── Strict response models (replace FastAPI built-ins) ────────────────────────


class ProdMCPValidationDetail(BaseModel):
    """Strict validation error detail — replaces FastAPI's built-in ``ValidationError``.

    All string fields have explicit ``max_length`` and ``pattern`` so no bare
    strings appear in the generated OpenAPI schema.
    """
    model_config = ConfigDict(extra="forbid", json_schema_extra=_harden_anyof_in_schema)
    loc: list[str] = Field(
        default_factory=list,
        max_length=20,
        description="Error location",
        json_schema_extra={
            "items": {"type": "string", "maxLength": 128, "pattern": r"^[a-zA-Z0-9_\[\].-]+$"}
        }
    )
    msg: str = Field(..., max_length=512, pattern=r"^[\s\S]{0,512}$", description="Error message")
    type: str = Field(..., max_length=64, pattern=r"^[\w.\-]+$", description="Error type")


class ProdMCPHTTPValidationError(BaseModel):
    """Strict HTTP validation error — replaces FastAPI's ``HTTPValidationError``."""
    model_config = ConfigDict(extra="forbid", json_schema_extra=_harden_anyof_in_schema)
    detail: list[ProdMCPValidationDetail] = Field(
        default_factory=list, max_length=100, description="Validation errors"
    )


class ErrorDetail(BaseModel):
    """Strict error response body for 401/403/500 responses."""
    model_config = ConfigDict(extra="forbid", json_schema_extra=_harden_anyof_in_schema)
    detail: str = Field(
        ...,
        max_length=256,
        pattern=r"^[\w\s.,!?:;\-'\"()]+$",
        description="Human-readable error message",
    )


# ── Shared response declarations (registered at route creation time) ──────────

# Core error responses that should be on nearly every route
# 422 replaces FastAPI's default HTTPValidationError with our strict model.
VALIDATION_ERROR_RESPONSE: dict[int | str, dict[str, Any]] = {
    422: {
        "model": ProdMCPHTTPValidationError,
        "description": "Validation Error",
    },
}

AUTH_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {
        "model": ErrorDetail,
        "description": "Unauthorized — missing or invalid authentication credentials",
    },
    403: {
        "model": ErrorDetail,
        "description": "Forbidden — insufficient permissions for this operation",
    },
}

# Standard protocol error responses for 42Crunch compliance
# RFC 7231, RFC 6585 requirements for production-grade APIs
STANDARD_PROTOCOL_RESPONSES: dict[int | str, dict[str, Any]] = {
    406: {
        "model": ErrorDetail,
        "description": "Not Acceptable — the server cannot produce a response matching the list of acceptable values",
    },
    429: {
        "model": ErrorDetail,
        "description": "Too Many Requests — rate limit exceeded",
    },
    "default": {
        "model": ErrorDetail,
        "description": "Unexpected Error — catch-all for undeclared responses",
    },
}

# Specific to operations receiving a body (POST, PUT, PATCH)
PAYLOAD_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    415: {
        "model": ErrorDetail,
        "description": "Unsupported Media Type — the request body is in a format not supported by this endpoint",
    },
}


def _extract_output_description(output_schema: Any) -> str:
    """Derive a human-readable 200 response description from the output schema.

    Strategy:
    - Single BaseModel → use its class docstring (Pydantic exposes it as
      ``model_json_schema()["description"]`` and also as ``__doc__``).
    - ``Union[A, B, ...]`` / ``Optional[X]`` → compose per-variant descriptions
      as ``"ModelA: <desc> | ModelB: <desc>"`` so each variant is self-documented.
    - dict-schema → use the top-level ``description`` key if present.
    - Anything else → fall back to ``"Successful Response"``.
    """
    if output_schema is None:
        return "Successful Response"

    from pydantic import BaseModel as _BM

    # ── Single Pydantic model ──────────────────────────────────────────────────
    if isinstance(output_schema, type) and issubclass(output_schema, _BM):
        doc = (output_schema.__doc__ or "").strip()
        # Strip the generic Pydantic auto-doc if present
        if doc and not doc.startswith("Usage docs:"):
            return doc
        # Fall back to model_json_schema description
        schema_desc = output_schema.model_json_schema().get("description", "")
        return schema_desc.strip() or "Successful Response"

    # ── dict schema with a top-level description ───────────────────────────────
    if isinstance(output_schema, dict):
        return (output_schema.get("description") or "Successful Response").strip()

    # ── Union / Optional — inspect __args__ ──────────────────────────────────
    import typing
    args = getattr(output_schema, "__args__", None)
    if args:
        parts: list[str] = []
        for arg in args:
            # Skip NoneType (from Optional)
            if arg is type(None):
                continue
            if isinstance(arg, type) and issubclass(arg, _BM):
                doc = (arg.__doc__ or "").strip()
                if doc and not doc.startswith("Usage docs:"):
                    parts.append(f"{arg.__name__}: {doc}")
                else:
                    parts.append(arg.__name__)
            else:
                name = getattr(arg, "__name__", repr(arg))
                parts.append(name)
        if parts:
            return " | ".join(parts)

    return "Successful Response"



def create_fastapi_app(app: "ProdMCP", title: str | None = None) -> FastAPI:
    """Create a FastAPI application from a ProdMCP instance."""
    app_title = title or app.name or "ProdMCP Server"

    fastapi_kwargs: dict[str, Any] = {
        "title": app_title,
        "version": app.version,
        "description": app.description,
    }
    if app.servers:
        fastapi_kwargs["servers"] = app.servers
    fastapi_app = FastAPI(**fastapi_kwargs)

    # ── Apply ASGI-level middlewares (e.g. CORSMiddleware) ─────────────
    # Mirrors create_unified_app() — same registered configs must be applied
    # here so that app.test_mcp_as_fastapi() / app.test_mcp_as_fastapi() also get
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
                v_clean = {k2: v2 for k2, v2 in v.items() if k2 not in ("title", "description")}
                fields[k] = (Any, Field(... if is_req else None, json_schema_extra=v_clean if v_clean else None))
            
            # Using ConfigDict locally guarantees all auto-generated schemas block unexpected properties
            m = create_model(name, __config__=ConfigDict(extra="forbid"), **fields)
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

    # Inject ProdMCP security schemes into the generated OpenAPI spec
    _inject_security_into_openapi(fastapi_app, app)

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

    # Extract actual parameter annotations natively to preserve full Pydantic models and $refs
    import inspect
    sig = inspect.signature(handler_fn)
    fields = {}
    for p_name, p in sig.parameters.items():
        if p_name == "ctx": continue
        annotation = p.annotation if p.annotation != inspect.Parameter.empty else Any
        default = p.default if p.default != inspect.Parameter.empty else ...
        fields[p_name] = (annotation, default)
    
    from pydantic import create_model, ConfigDict
    model_class = None
    if fields:
        model_class = create_model(
            f"Tool{name.capitalize()}Input",
            __config__=ConfigDict(extra="forbid"),
            **fields
        )

    # Harden output model at registration time — ensures additionalProperties:false
    # and anyOf hardening come from the model itself, not from post-patching.
    response_model = None
    if out_schema is not None:
        if isinstance(out_schema, type) and issubclass(out_schema, BaseModel):
            response_model = _ensure_strict_model(out_schema)

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

    route_kwargs: dict[str, Any] = {
        "methods": ["POST"],
        "summary": f"Execute tool: {name}",
        "description": meta["description"],
    }
    if response_model is not None:
        route_kwargs["response_model"] = response_model

    # Derive the 200 response description from the output model docstring(s)
    response_200_desc = _extract_output_description(out_schema)

    # Declare all error responses at route creation time:
    responses: dict[int | str, dict[str, Any]] = {
        200: {"description": response_200_desc},
        **VALIDATION_ERROR_RESPONSE,
        **STANDARD_PROTOCOL_RESPONSES,
        **PAYLOAD_ERROR_RESPONSES,
    }
    if meta.get("security"):
        responses.update(AUTH_ERROR_RESPONSES)
    route_kwargs["responses"] = responses

    fastapi_app.add_api_route(f"/tools/{name}", handler_to_use, **route_kwargs)


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

    import inspect
    sig = inspect.signature(handler_fn)
    fields = {}
    for p_name, p in sig.parameters.items():
        if p_name == "ctx": continue
        annotation = p.annotation if p.annotation != inspect.Parameter.empty else Any
        default = p.default if p.default != inspect.Parameter.empty else ...
        fields[p_name] = (annotation, default)
    
    from pydantic import create_model, ConfigDict
    model_class = None
    if fields:
        model_class = create_model(
            f"Prompt{name.capitalize()}Input",
            __config__=ConfigDict(extra="forbid"),
            **fields
        )

    # D8/E2 fix: reuse the pre-built wrapped handler stored during _register_prompt.
    # Previously _build_handler() was always called here, causing double middleware
    # wrapping in test_mcp_as_fastapi() / test_mcp_as_fastapi() — LoggingMiddleware fired twice.
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
        responses={
            200: {"description": _extract_output_description(out_schema)},
            **VALIDATION_ERROR_RESPONSE,
            **STANDARD_PROTOCOL_RESPONSES,
            **PAYLOAD_ERROR_RESPONSES,
        },
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
        responses={
            **VALIDATION_ERROR_RESPONSE,
            **STANDARD_PROTOCOL_RESPONSES,
        },
    )


def _inject_security_into_openapi(fastapi_app: FastAPI, app: "ProdMCP") -> None:
    """Inject ProdMCP security schemes into the FastAPI OpenAPI schema.

    ProdMCP manages security independently of FastAPI's native Depends-based
    security.  The runtime enforcement (via _wrap_with_security) works correctly,
    but the generated OpenAPI spec is missing:

      1. ``components.securitySchemes`` — scheme definitions (e.g. bearerAuth)
      2. Per-operation ``security`` requirements — which routes require auth

    This function patches ``fastapi_app.openapi()`` to inject both after
    FastAPI's default schema generation runs.
    """
    schemes = app._security_manager.generate_schemes_spec()

    # Collect per-path security requirements from tools, prompts, and resources
    path_security: dict[str, list] = {}
    for name, meta in app._registry.get("tools", {}).items():
        sec = meta.get("security")
        if sec:
            path_security[f"/tools/{name}"] = app._security_manager.generate_security_spec(sec)

    for name, meta in app._registry.get("prompts", {}).items():
        sec = meta.get("security")
        if sec:
            path_security[f"/prompts/{name}"] = app._security_manager.generate_security_spec(sec)

    # Resources share a single wildcard path
    resource_sec = None
    for _name, meta in app._registry.get("resources", {}).items():
        sec = meta.get("security")
        if sec:
            resource_sec = app._security_manager.generate_security_spec(sec)
            break
    if resource_sec:
        path_security["/resources/{mcp_uri}"] = resource_sec

    # Build global security requirements: the union of all registered scheme names
    global_security: list[dict] = []
    if schemes:
        global_security = [{name: []} for name in schemes]

    # Nothing to inject
    if not schemes and not path_security:
        return

    _original_openapi = fastapi_app.openapi

    def _patched_openapi() -> dict:  # type: ignore[override]
        if fastapi_app.openapi_schema:
            return fastapi_app.openapi_schema

        schema = _original_openapi()

        # 1. Inject securitySchemes into components
        if schemes:
            components = schema.setdefault("components", {})
            sec_schemes = components.setdefault("securitySchemes", {})
            sec_schemes.update(schemes)

        # 2. Inject global security field (default for ALL operations)
        if global_security:
            schema["security"] = global_security

        # 3. Inject per-route security overrides (explicit per-operation)
        paths = schema.get("paths", {})
        for path, sec_reqs in path_security.items():
            if path in paths:
                for method_spec in paths[path].values():
                    if isinstance(method_spec, dict):
                        method_spec["security"] = sec_reqs


        # 3. Fix bare response schemas — ensure all response schemas have
        #    at least "type": "object" so API security scanners (42Crunch)
        #    don't flag them as accepting arbitrary payloads.
        for _path, path_item in paths.items():
            for _method, method_spec in path_item.items():
                if not isinstance(method_spec, dict):
                    continue
                for _status, resp in method_spec.get("responses", {}).items():
                    if not isinstance(resp, dict):
                        continue
                    for _media, media_obj in resp.get("content", {}).items():
                        if not isinstance(media_obj, dict):
                            continue
                        resp_schema = media_obj.get("schema", {})
                        if (
                            isinstance(resp_schema, dict)
                            and "type" not in resp_schema
                            and "$ref" not in resp_schema
                            and "allOf" not in resp_schema
                            and "anyOf" not in resp_schema
                            and "oneOf" not in resp_schema
                        ):
                            resp_schema["type"] = "object"

        # Steps 4-7 eliminated: all schema hardening is now at the source.
        # - additionalProperties:false → _ensure_strict_model at registration
        # - anyOf hardening → json_schema_extra on models
        # - 401/403 → AUTH_ERROR_RESPONSES at route creation
        # - 422 → VALIDATION_ERROR_RESPONSE at route creation
        # - string defaults → ProdMCPValidationDetail/ErrorDetail models

        # Clean up: remove unreferenced FastAPI built-in schemas that may
        # have been added by FastAPI's internal machinery despite our
        # 422 override.  This is a filter (removing unused entries), not
        # a schema modification.
        _remove_unreferenced_builtins(schema)

        fastapi_app.openapi_schema = schema
        return schema

    fastapi_app.openapi = _patched_openapi  # type: ignore[method-assign]


def _remove_unreferenced_builtins(schema: dict) -> None:
    """Remove FastAPI's built-in HTTPValidationError/ValidationError schemas
    if they are not referenced by any $ref in the paths section.  ProdMCP
    replaces these with its own strict models (ProdMCPHTTPValidationError etc.)."""
    schemas = schema.get("components", {}).get("schemas", {})
    builtins = {"HTTPValidationError", "ValidationError"}
    present = builtins & set(schemas.keys())
    if not present:
        return
    # Check references only in paths (not in component schemas themselves)
    import json
    paths_str = json.dumps(schema.get("paths", {}))
    for name in list(present):
        ref_str = f"#/components/schemas/{name}"
        if ref_str not in paths_str:
            del schemas[name]


def _harden_nested_anyof(schema: dict) -> None:
    """Walk all schemas and add ``additionalProperties: false`` to primitive anyOf/oneOf.

    Pydantic v2 generates ``anyOf: [{type: "string"}, {type: "null"}]`` for
    ``Optional[str]`` fields.  42Crunch flags these because ``additionalProperties``
    defaults to ``true``.  Per 42Crunch guidance, primitive anyOf/oneOf (no
    ``properties`` key in any sub-schema) can safely set ``additionalProperties: false``.

    This function also handles the ``items`` key inside array properties (e.g.
    ``ValidationError.loc`` which has ``items: {anyOf: [...]}``)  and any deeply
    nested structure.
    """
    for comp_schema in schema.get("components", {}).get("schemas", {}).values():
        if isinstance(comp_schema, dict):
            _walk_and_harden(comp_schema)


def _walk_and_harden(node: dict) -> None:
    """Recursively walk a schema node and harden anyOf/oneOf primitives."""
    if not isinstance(node, dict):
        return

    # Process properties
    for prop in node.get("properties", {}).values():
        if isinstance(prop, dict):
            _apply_anyof_fix(prop)
            _walk_and_harden(prop)

    # Process items (array schemas)
    items = node.get("items")
    if isinstance(items, dict):
        _apply_anyof_fix(items)
        _walk_and_harden(items)


def _apply_anyof_fix(prop: dict) -> None:
    """Add additionalProperties: false to a property's anyOf/oneOf if all sub-schemas are primitives."""
    for key in ("anyOf", "oneOf"):
        sub_schemas = prop.get(key)
        if not isinstance(sub_schemas, list):
            continue
        # Check if ALL sub-schemas are primitives (no "properties" key)
        all_primitive = all(
            isinstance(s, dict) and "properties" not in s
            for s in sub_schemas
        )
        if all_primitive and "additionalProperties" not in prop:
            prop["additionalProperties"] = False


def _inject_auth_error_responses(schema: dict) -> None:
    """Inject 401/403 responses on operations that have ``security`` defined.

    42Crunch requires secured operations to declare both 401 (Unauthorized)
    and 403 (Forbidden) responses.  FastAPI doesn't add these by default,
    so ProdMCP injects them during OpenAPI post-processing.
    """
    _ERROR_SCHEMA = {
        "application/json": {
            "schema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "detail": {
                        "type": "string",
                        "maxLength": 256,
                        "pattern": "^[\\w\\s.,!?:;\\-'\"()]+$",
                    }
                },
                "required": ["detail"],
            }
        }
    }

    for path_item in schema.get("paths", {}).values():
        for method_obj in path_item.values():
            if not isinstance(method_obj, dict):
                continue
            # Check for security at operation level or global level
            has_security = (
                method_obj.get("security")
                or schema.get("security")
            )
            if not has_security:
                continue

            responses = method_obj.setdefault("responses", {})
            if "401" not in responses:
                responses["401"] = {
                    "description": "Unauthorized — missing or invalid authentication credentials",
                    "content": _ERROR_SCHEMA,
                }
            if "403" not in responses:
                responses["403"] = {
                    "description": "Forbidden — insufficient permissions for this operation",
                    "content": _ERROR_SCHEMA,
                }


# Default boundaries for bare strings (generous — won't break legitimate data)
_DEFAULT_MAX_LENGTH = 1024
_DEFAULT_PATTERN = r"^[\s\S]{0,1024}$"


def _set_string_defaults(schema: dict) -> None:
    """Add ``maxLength`` and ``pattern`` to bare string properties in component schemas.

    FastAPI built-in models (``ValidationError``, ``HTTPValidationError``) define
    string properties without any boundaries.  42Crunch flags these as security
    risks.  This function injects generous defaults on any string property that
    lacks them.
    """
    for comp_schema in schema.get("components", {}).get("schemas", {}).values():
        if isinstance(comp_schema, dict):
            _walk_and_set_string_defaults(comp_schema)


def _walk_and_set_string_defaults(node: dict) -> None:
    """Recursively walk schema properties and set string defaults."""
    if not isinstance(node, dict):
        return

    for prop in node.get("properties", {}).values():
        if not isinstance(prop, dict):
            continue

        # Direct string property
        if prop.get("type") == "string":
            if "maxLength" not in prop:
                prop["maxLength"] = _DEFAULT_MAX_LENGTH
            if "pattern" not in prop:
                prop["pattern"] = _DEFAULT_PATTERN

        # Strings inside anyOf/oneOf (e.g. Optional[str])
        for key in ("anyOf", "oneOf"):
            for sub in prop.get(key, []):
                if isinstance(sub, dict) and sub.get("type") == "string":
                    if "maxLength" not in sub and "maxLength" not in prop:
                        prop["maxLength"] = _DEFAULT_MAX_LENGTH
                    if "pattern" not in sub and "pattern" not in prop:
                        prop["pattern"] = _DEFAULT_PATTERN

        # Recurse into nested objects
        _walk_and_set_string_defaults(prop)

    # Recurse into array items
    items = node.get("items")
    if isinstance(items, dict):
        if items.get("type") == "string":
            if "maxLength" not in items:
                items["maxLength"] = _DEFAULT_MAX_LENGTH
            if "pattern" not in items:
                items["pattern"] = _DEFAULT_PATTERN
        _walk_and_set_string_defaults(items)

