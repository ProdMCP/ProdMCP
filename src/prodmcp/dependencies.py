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
        if isinstance(default, Depends):
            dep_key = default.dependency  # C1 fix: hashable callable, not id()

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
    1. Parameters named exactly ``"context"`` receive the full request context dict.
    2. Parameters annotated as ``dict`` (or ``dict[str, Any]``) receive the context.
    3. Parameters with a ``Depends()`` default are resolved recursively.
    4. Parameters that have a non-Depends default use that default (not injected).
    5. Any required parameter that cannot be resolved triggers a ``UserWarning``
       (the call will then fail with ``TypeError``, surfacing the real error).
    """
    sig = inspect.signature(dep_fn)
    kwargs: dict[str, Any] = {}

    for param_name, param in sig.parameters.items():
        if isinstance(param.default, Depends):
            # Nested dependency — resolve recursively
            nested = await _call_dependency(param.default.dependency, context)
            kwargs[param_name] = nested
        elif _param_wants_context(param_name, param):
            # C2 fix: inject context for params named 'context' OR annotated as dict.
            # Previously ONLY the literal name 'context' was handled; any other
            # param name (e.g. 'ctx', 'request_context', 'headers: dict') would
            # silently receive no value and cause a TypeError at call time.
            kwargs[param_name] = context
        elif param.default is inspect.Parameter.empty:
            # C2 fix: required param with no default and no injection path.
            # Warn so developers see the misconfiguration instead of a cryptic TypeError.
            import warnings
            warnings.warn(
                f"Dependency {getattr(dep_fn, '__name__', repr(dep_fn))!r}: "
                f"required parameter {param_name!r} cannot be resolved from the "
                "request context. Name it 'context' or annotate it as 'dict' to "
                "receive the context dict, or give it a default value.",
                UserWarning,
                stacklevel=3,
            )
        # else: has a non-Depends default — Python will use it automatically

    if inspect.iscoroutinefunction(dep_fn):
        return await dep_fn(**kwargs)
    return dep_fn(**kwargs)


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
