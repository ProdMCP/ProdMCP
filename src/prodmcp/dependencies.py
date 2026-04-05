"""Dependency injection system for ProdMCP.

Provides a FastAPI-like ``Depends()`` mechanism for injecting
resolved values into handler functions.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class Depends:
    """Marker for a dependency that should be resolved at call time.

    Usage:
        def get_current_user(context):
            return context.get("user")

        @app.tool(name="my_tool")
        def my_handler(user=Depends(get_current_user)):
            ...
    """

    dependency: Callable[..., Any]
    use_cache: bool = True

    def __repr__(self) -> str:
        name = getattr(self.dependency, "__name__", str(self.dependency))
        return f"Depends({name})"


async def resolve_dependencies(
    fn: Callable[..., Any],
    context: dict[str, Any],
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Inspect a function's signature and resolve Depends() defaults.

    Args:
        fn: The handler function to inspect.
        context: The request context dict (passed to each dependency callable).
        overrides: Optional dict of pre-resolved values (skip dependency resolution).
            Note: an override key that matches a Depends() parameter NAME will
            bypass that dependency — this is intentional for testing.

    Returns:
        A dict of parameter_name -> resolved_value for all Depends() parameters.

    Note:
        ``use_cache=True`` (the default on :class:`Depends`) is **request-scoped**
        only -- it de-duplicates the same callable within a single handler
        invocation, not across multiple requests.
    """
    overrides = overrides or {}
    resolved: dict[str, Any] = {}
    # C1 fix: key by the callable object itself, not id().
    # id() returns the memory address; after GC, two different lambdas may share
    # an address, causing a stale cached value to be returned for the new callable.
    # Python functions/lambdas are hashable by identity, so using them as dict keys
    # is both correct and GC-stable.
    cache: dict[Any, Any] = {}

    sig = inspect.signature(fn)
    for param_name, param in sig.parameters.items():
        # Skip if already provided via overrides
        if param_name in overrides:
            resolved[param_name] = overrides[param_name]
            continue

        default = param.default
        # Bug 3/5 fix: duck-type Depends detection — recognise fastapi.Depends too.
        # Both prodmcp.Depends and fastapi.Depends expose a .dependency callable.
        is_depends = isinstance(default, Depends) or (
            default is not inspect.Parameter.empty
            and hasattr(default, "dependency")
            and callable(getattr(default, "dependency", None))
        )
        if is_depends:
            dep_key = default.dependency  # hashable callable (C1 fix)

            # Use cached result if allowed
            if default.use_cache and dep_key in cache:
                resolved[param_name] = cache[dep_key]
                continue

            # Resolve the dependency
            dep_fn = default.dependency
            value = await _call_dependency(dep_fn, context)

            if default.use_cache:
                cache[dep_key] = value
            resolved[param_name] = value

    return resolved


async def _call_dependency(
    dep_fn: Callable[..., Any],
    context: dict[str, Any],
) -> Any:
    """Call a dependency function, supporting both sync and async.

    Context injection rules (in priority order):
    1. Parameters with a ``Depends()`` default (ProdMCP *or* FastAPI duck-type)
       are resolved recursively.
    2. Parameters named ``"context"`` or annotated as ``dict`` receive the full
       request context dict.
    3. Parameters whose type annotation is ``HTTPAuthorizationCredentials`` or
       whose name is ``"credentials"``/``"authorization"`` are synthesised from
       the ``Authorization`` request header.
    4. Parameters whose name matches a top-level key in the context dict receive
       that value directly (e.g. ``headers``, ``query_params``, ``cookies``).
    5. Any remaining required parameter (no default, no injection path) emits a
       ``UserWarning`` — the call will then fail with ``TypeError``.
    """
    sig = inspect.signature(dep_fn)
    kwargs: dict[str, Any] = {}

    for param_name, param in sig.parameters.items():
        param_default = param.default

        # Rule 1: Depends() — duck-typed to support both prodmcp.Depends and fastapi.Depends
        # Bug 5 fix: the old code only checked isinstance(param.default, Depends),
        # which missed fastapi.Depends. Use the same duck-type heuristic as Bug 3.
        is_depends = isinstance(param_default, Depends) or (
            param_default is not inspect.Parameter.empty
            and hasattr(param_default, "dependency")
            and callable(getattr(param_default, "dependency", None))
        )
        if is_depends:
            nested = await _call_dependency(param_default.dependency, context)
            kwargs[param_name] = nested
            continue

        # Rule 2: context-typed params (name == "context" or annotated as dict)
        if _param_wants_context(param_name, param):
            kwargs[param_name] = context
            continue

        # Rule 3: credentials-typed params — synthesise from Authorization header.
        # Bug 5 fix: FastAPI's idiomatic auth pattern uses parameters named
        # "credentials" with type HTTPAuthorizationCredentials (or similar).
        # ProdMCP's context dict stores headers but never injected them for
        # non-"context"-named params, so the entire auth chain produced None.
        annotation = param.annotation
        annotation_name = getattr(annotation, "__name__", "") or getattr(
            getattr(annotation, "__class__", None), "__name__", ""
        )
        is_credentials_param = (
            param_name in ("credentials", "authorization")
            or "AuthorizationCredentials" in annotation_name
            or "Credentials" in annotation_name
        )
        if is_credentials_param:
            cred_obj = _extract_credentials(context)
            if cred_obj is not None:
                kwargs[param_name] = cred_obj
            # else: leave unset — Python will use the default (or TypeError on call)
            continue

        # Rule 4: inject by matching context key directly (e.g. headers, query_params)
        if param_name in context:
            kwargs[param_name] = context[param_name]
            continue

        # Rule 5: required param with no injection path — warn
        if param_default is inspect.Parameter.empty:
            import warnings
            warnings.warn(
                f"Dependency {getattr(dep_fn, '__name__', repr(dep_fn))!r}: "
                f"required parameter {param_name!r} cannot be resolved from the "
                "request context. Name it 'context', annotate it as 'dict', or "
                "give it a default value.",
                UserWarning,
                stacklevel=3,
            )
        # else: has a non-Depends default — Python will use it automatically

    if inspect.iscoroutinefunction(dep_fn):
        return await dep_fn(**kwargs)
    return dep_fn(**kwargs)


def _extract_credentials(context: dict[str, Any]) -> Any:
    """Extract an HTTPAuthorizationCredentials-like object from the request context.

    Parses the ``Authorization`` header (case-insensitive) and returns an object
    with ``.scheme`` and ``.credentials`` attributes, compatible with FastAPI's
    ``HTTPAuthorizationCredentials``.

    Returns ``None`` if no Authorization header is present.
    """
    headers: dict[str, str] = context.get("headers", {})
    # Headers dict from FastAPI/Starlette uses lowercase keys
    auth_value = headers.get("authorization") or headers.get("Authorization", "")
    if not auth_value:
        return None

    scheme, _, credentials = auth_value.partition(" ")
    if not credentials:
        # Malformed — treat entire value as credentials with empty scheme
        scheme, credentials = "", auth_value

    # Return a lightweight credentials object compatible with FastAPI's
    # HTTPAuthorizationCredentials (duck-typed — no FastAPI import required).
    class _Credentials:
        def __init__(self, scheme: str, credentials: str) -> None:
            self.scheme = scheme
            self.credentials = credentials

        def __repr__(self) -> str:
            return f"Credentials(scheme={self.scheme!r})"

    return _Credentials(scheme=scheme, credentials=credentials)


def _param_wants_context(param_name: str, param: inspect.Parameter) -> bool:
    """Return True if this parameter should receive the request context dict.

    Matches:
    - Parameters literally named ``"context"``
    - Parameters whose annotation is ``dict`` or a generic ``dict[...]``
    """
    if param_name == "context":
        return True
    annotation = param.annotation
    if annotation is inspect.Parameter.empty:
        return False
    if annotation is dict:
        return True
    # dict[str, Any] and similar generics
    return getattr(annotation, "__origin__", None) is dict
