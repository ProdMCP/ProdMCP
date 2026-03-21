"""Middleware system for ProdMCP.

Provides global before/after hooks that wrap handler execution.
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from typing import Any, Callable, Awaitable

logger = logging.getLogger(__name__)


class MiddlewareContext:
    """Context object passed through middleware hooks.

    Attributes:
        entity_type: 'tool', 'prompt', or 'resource'.
        entity_name: Name of the entity being invoked.
        args: Positional arguments to the handler.
        kwargs: Keyword arguments to the handler.
        metadata: Arbitrary metadata dict for middleware communication.
        result: The handler's return value (available in ``after``).
        error: Any exception raised during execution (available in ``after``).
    """

    def __init__(
        self,
        entity_type: str,
        entity_name: str,
        args: tuple[Any, ...] = (),
        kwargs: dict[str, Any] | None = None,
    ) -> None:
        self.entity_type = entity_type
        self.entity_name = entity_name
        self.args = args
        self.kwargs = kwargs or {}
        self.metadata: dict[str, Any] = {}
        self.result: Any = None
        self.error: Exception | None = None


class Middleware(ABC):
    """Base class for ProdMCP middleware.

    Subclass and implement ``before`` and/or ``after`` hooks.
    """

    @abstractmethod
    async def before(self, context: MiddlewareContext) -> None:
        """Called before handler execution.

        Modify ``context.kwargs`` or ``context.metadata`` as needed.
        Raise an exception to abort execution.
        """

    @abstractmethod
    async def after(self, context: MiddlewareContext) -> None:
        """Called after handler execution.

        ``context.result`` contains the handler return value.
        ``context.error`` contains any exception (if raised).
        """


class LoggingMiddleware(Middleware):
    """Built-in middleware that logs handler invocations."""

    def __init__(self, log_level: int = logging.INFO) -> None:
        self.log_level = log_level

    async def before(self, context: MiddlewareContext) -> None:
        context.metadata["_start_time"] = time.monotonic()
        logger.log(
            self.log_level,
            "[ProdMCP] %s '%s' called with kwargs=%s",
            context.entity_type,
            context.entity_name,
            list(context.kwargs.keys()),
        )

    async def after(self, context: MiddlewareContext) -> None:
        elapsed = time.monotonic() - context.metadata.get("_start_time", 0)
        if context.error:
            logger.log(
                logging.ERROR,
                "[ProdMCP] %s '%s' failed in %.3fs: %s",
                context.entity_type,
                context.entity_name,
                elapsed,
                context.error,
            )
        else:
            logger.log(
                self.log_level,
                "[ProdMCP] %s '%s' completed in %.3fs",
                context.entity_type,
                context.entity_name,
                elapsed,
            )


class MiddlewareManager:
    """Manages and executes a chain of middleware."""

    def __init__(self) -> None:
        self._global: list[Middleware] = []
        self._named: dict[str, Middleware] = {}

    def add(self, middleware: Middleware | type, name: str | None = None) -> None:
        """Register a global middleware instance or class.

        Args:
            middleware: A Middleware instance or class.
            name: Optional name for referencing in per-entity middleware lists.
        """
        if isinstance(middleware, type):
            middleware = middleware()
        self._global.append(middleware)
        if name:
            self._named[name] = middleware

    def register_named(self, name: str, middleware: Middleware) -> None:
        """Register a named middleware without adding it to the global chain."""
        self._named[name] = middleware

    def get_chain(
        self,
        entity_middleware: list[str | Middleware] | None = None,
    ) -> list[Middleware]:
        """Build the middleware chain for a specific entity.

        Global middleware runs first, then entity-specific middleware.

        Args:
            entity_middleware: Optional list of middleware names or instances.

        Returns:
            Ordered list of Middleware instances.
        """
        chain = list(self._global)
        if entity_middleware:
            for mw in entity_middleware:
                if isinstance(mw, str):
                    named = self._named.get(mw)
                    if named and named not in chain:
                        chain.append(named)
                elif isinstance(mw, Middleware):
                    if mw not in chain:
                        chain.append(mw)
        return chain

    async def execute_before(
        self, chain: list[Middleware], context: MiddlewareContext
    ) -> None:
        """Run all before hooks in order."""
        for mw in chain:
            await mw.before(context)

    async def execute_after(
        self, chain: list[Middleware], context: MiddlewareContext
    ) -> None:
        """Run all after hooks in reverse order."""
        for mw in reversed(chain):
            await mw.after(context)


def build_middleware_chain(
    handler: Callable[..., Any],
    middleware_manager: MiddlewareManager,
    entity_middleware: list[str | Middleware] | None,
    entity_type: str,
    entity_name: str,
) -> Callable[..., Awaitable[Any]]:
    """Wrap a handler with middleware before/after hooks.

    Returns an async callable that executes middleware around the handler.
    The returned function preserves the original handler's signature so that
    FastMCP can correctly inspect its parameters.
    """
    import functools
    import inspect

    chain = middleware_manager.get_chain(entity_middleware)

    @functools.wraps(handler)
    async def wrapped(**kwargs: Any) -> Any:
        context = MiddlewareContext(
            entity_type=entity_type,
            entity_name=entity_name,
            args=(),
            kwargs=kwargs,
        )

        # Before hooks
        await middleware_manager.execute_before(chain, context)
        # Update kwargs in case middleware modified them
        kwargs = context.kwargs

        try:
            import asyncio
            if asyncio.iscoroutinefunction(handler):
                result = await handler(**kwargs)
            else:
                result = handler(**kwargs)
            context.result = result
        except Exception as exc:
            context.error = exc
            await middleware_manager.execute_after(chain, context)
            raise

        # After hooks
        await middleware_manager.execute_after(chain, context)
        return context.result

    # Copy the original function's signature so FastMCP can inspect parameters
    wrapped.__signature__ = inspect.signature(handler)
    return wrapped
