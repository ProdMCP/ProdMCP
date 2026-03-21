"""Dependency injection system for ProdMCP.

Provides a FastAPI-like ``Depends()`` mechanism for injecting
resolved values into handler functions.
"""

from __future__ import annotations

import asyncio
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

    Returns:
        A dict of parameter_name -> resolved_value for all Depends() parameters.
    """
    overrides = overrides or {}
    resolved: dict[str, Any] = {}
    cache: dict[int, Any] = {}

    sig = inspect.signature(fn)
    for param_name, param in sig.parameters.items():
        # Skip if already provided via overrides
        if param_name in overrides:
            resolved[param_name] = overrides[param_name]
            continue

        default = param.default
        if isinstance(default, Depends):
            dep_key = id(default.dependency)

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
    """Call a dependency function, supporting both sync and async."""
    sig = inspect.signature(dep_fn)
    kwargs: dict[str, Any] = {}

    for param_name, param in sig.parameters.items():
        if param_name == "context":
            kwargs["context"] = context
        elif isinstance(param.default, Depends):
            # Nested dependency
            nested = await _call_dependency(param.default.dependency, context)
            kwargs[param_name] = nested

    if asyncio.iscoroutinefunction(dep_fn):
        return await dep_fn(**kwargs)
    return dep_fn(**kwargs)
