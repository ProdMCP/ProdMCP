"""FastAPI bridge for ProdMCP.

Auto-generates a FastAPI application from a registered ProdMCP instance.
"""

from __future__ import annotations

import inspect
import logging
from typing import TYPE_CHECKING, Any, Callable, Type

try:
    from fastapi import Depends, FastAPI, HTTPException, Request
    from pydantic import BaseModel, create_model
except ImportError as exc:
    raise ImportError(
        "FastAPI is required for the REST bridge. "
        "Install it with `pip install prodmcp[rest]`."
    ) from exc

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from .app import ProdMCP


def create_fastapi_app(app: "ProdMCP", title: str | None = None) -> FastAPI:
    """Create a FastAPI application from a ProdMCP instance."""
    app_title = title or app.name or "ProdMCP Server"
    fastapi_app = FastAPI(
        title=app_title, version=app.version, description=app.description
    )

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

    # Map Prompts
    for name, meta in app._registry["prompts"].items():
        _add_prompt_route(
            fastapi_app, name, meta, _ensure_pydantic
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
        try:
            if is_async:
                return await wrapped_handler(**kwargs)
            return wrapped_handler(**kwargs)
        except Exception as e:
            from fastapi import HTTPException
            from .exceptions import ProdMCPSecurityError, ProdMCPValidationError

            if isinstance(e, ProdMCPSecurityError):
                raise HTTPException(status_code=403, detail=str(e)) from e
            if isinstance(e, ProdMCPValidationError):
                raise HTTPException(
                    status_code=422, detail={"errors": e.errors, "message": str(e)}
                ) from e
            if isinstance(e, HTTPException):
                raise
            raise HTTPException(status_code=500, detail=str(e)) from e

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
            kwargs = dict(body)
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
    name: str,
    meta: dict[str, Any],
    _ensure_pydantic: Callable,
) -> None:
    handler_fn = meta["handler"]
    in_schema = meta["input_schema"]
    out_schema = meta["output_schema"]

    model_class = _ensure_pydantic(f"Prompt{name.capitalize()}Input", in_schema)

    from .validation import create_validated_handler

    wrapped_handler = create_validated_handler(
        handler_fn,
        input_schema=in_schema,
        output_schema=out_schema,
        strict=False,
    )
    is_async = inspect.iscoroutinefunction(wrapped_handler)

    async def _execute_wrapped(kwargs: dict[str, Any]) -> Any:
        try:
            if is_async:
                return await wrapped_handler(**kwargs)
            return wrapped_handler(**kwargs)
        except Exception as e:
            from fastapi import HTTPException
            from .exceptions import ProdMCPSecurityError, ProdMCPValidationError
            if isinstance(e, ProdMCPSecurityError):
                raise HTTPException(status_code=403, detail=str(e)) from e
            if isinstance(e, ProdMCPValidationError):
                raise HTTPException(
                    status_code=422, detail={"errors": e.errors, "message": str(e)}
                ) from e
            if isinstance(e, HTTPException):
                raise
            raise HTTPException(status_code=500, detail=str(e)) from e

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
            kwargs = dict(body)
            return await _execute_wrapped(kwargs)

        handler_to_use = dict_route_handler

    fastapi_app.add_api_route(
        f"/prompts/{name}",
        handler_to_use,
        methods=["POST"],
        summary=f"Execute prompt: {name}",
        description=meta["description"],
    )


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
        # mcp_uri comes from /resources/{mcp_uri:path} (url-encoded representation)
        try:
            # We bypass full wrapper injection here and rely directly on FastMCP 
            # for resource routing, but ProdMCP's FastMCP dependency injection does not cleanly
            # map `__security_context__` into FastMCP.
            # So we check security MANUALLY for all resources globally or specifically?
            # Actually, `ProdMCP` handles security on the wrapped resource handler inside `_registry["resources"]`.
            
            # Since fastmcp manages URI templates natively, we just invoke it:
            content = await app.mcp.read_resource(mcp_uri)
            return {"content": content}
        except Exception as e:
            if isinstance(e, HTTPException):
                raise
            raise HTTPException(status_code=404, detail=str(e)) from e

    fastapi_app.add_api_route(
        "/resources/{mcp_uri:path}",
        resource_route_handler,
        methods=["GET"],
        summary="Read any Resource by URI template",
    )
