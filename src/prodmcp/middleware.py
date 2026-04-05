"""Middleware system for ProdMCP.

Provides global before/after hooks that wrap handler execution,
and ASGI-level middleware registration for Starlette/FastAPI.
"""

from __future__ import annotations

import logging
import time
from abc import ABC
from dataclasses import dataclass, field
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

    Subclass and override :meth:`before` and/or :meth:`after` as needed.
    Both methods default to a no-op, so you only need to implement the
    hook(s) that are relevant to your middleware — no forced empty overrides.

    Example — a timing-only middleware::

        class TimingMiddleware(Middleware):
            async def before(self, ctx: MiddlewareContext) -> None:
                ctx.metadata["t0"] = time.monotonic()

            async def after(self, ctx: MiddlewareContext) -> None:
                elapsed = time.monotonic() - ctx.metadata["t0"]
                print(f"{ctx.entity_name} took {elapsed:.3f}s")
    """

    async def before(self, context: MiddlewareContext) -> None:
        """Called before handler execution.

        Modify ``context.kwargs`` or ``context.metadata`` as needed.
        Raise an exception to abort execution.
        Default: no-op.
        """

    async def after(self, context: MiddlewareContext) -> None:
        """Called after handler execution.

        ``context.result`` contains the handler return value.
        ``context.error`` contains any exception (if raised).
        Default: no-op.
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


@dataclass
class ASGIMiddlewareConfig:
    """Configuration for an ASGI-level (Starlette/FastAPI) middleware.

    Attributes:
        cls: The middleware class (e.g. CORSMiddleware).
        kwargs: Keyword arguments forwarded to the middleware constructor.
    """

    cls: type
    kwargs: dict[str, Any] = field(default_factory=dict)


class MiddlewareManager:
    """Manages and executes a chain of middleware.

    Tracks two distinct layers:
    - ProdMCP-level handlers (before/after hooks around tool/prompt/resource calls).
    - ASGI-level middlewares (Starlette/FastAPI, e.g. CORSMiddleware) that must
      be applied to the FastAPI app when ``create_unified_app()`` builds it.
    """

    def __init__(self) -> None:
        self._global: list[Middleware] = []
        self._named: dict[str, Middleware] = {}
        self._asgi: list[ASGIMiddlewareConfig] = []

    def add(self, middleware: Middleware | type, name: str | None = None) -> None:
        """Register a global ProdMCP-level middleware instance or class.

        Args:
            middleware: A Middleware instance or class.
            name: Optional name for per-entity referencing.
        """
        if isinstance(middleware, type):
            middleware = middleware()
        self._global.append(middleware)
        if name:
            self._named[name] = middleware

    def add_asgi(self, cls: type, **kwargs: Any) -> None:
        """Register an ASGI-level (Starlette/FastAPI) middleware.

        These are applied directly to the ``FastAPI`` application object via
        ``fastapi_app.add_middleware(cls, **kwargs)`` inside
        ``create_unified_app()``.  Use this for framework-level concerns such
        as CORS, GZip, TrustedHost, etc.

        Args:
            cls: Starlette/FastAPI middleware class (e.g. ``CORSMiddleware``).
            **kwargs: Arguments forwarded to the middleware constructor.
        """
        self._asgi.append(ASGIMiddlewareConfig(cls=cls, kwargs=kwargs))

    @property
    def asgi_middlewares(self) -> list[ASGIMiddlewareConfig]:
        """Return the ordered list of registered ASGI middleware configs."""
        return list(self._asgi)

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
                    elif not named:
                        # Gap 4 fix: a typo in middleware=["name"] was previously
                        # silently ignored.  Emit a warning so developers catch it.
                        import warnings
                        warnings.warn(
                            f"Named middleware {mw!r} not found in the registry. "
                            "Check for typos in your @app.tool(middleware=[...]) config. "
                            f"Registered names: {list(self._named.keys()) or '(none)'}",
                            UserWarning,
                            stacklevel=3,
                        )
                elif isinstance(mw, Middleware) and mw not in chain:
                    chain.append(mw)
        return chain

    async def execute_before(
        self, chain: list[Middleware], context: MiddlewareContext
    ) -> None:
        """Run all before hooks in order.

        .. deprecated::
            This method is not used by the ProdMCP runtime and lacks the
            before↔after pairing invariant. Use :func:`build_middleware_chain`
            to wrap handlers correctly.
        """
        import warnings
        warnings.warn(
            "MiddlewareManager.execute_before() is deprecated and unused by the runtime. "
            "Use build_middleware_chain() for proper before/after pairing guarantees.",
            DeprecationWarning,
            stacklevel=2,
        )
        for mw in chain:
            await mw.before(context)

    async def execute_after(
        self, chain: list[Middleware], context: MiddlewareContext
    ) -> None:
        """Run all after hooks in reverse order.

        .. deprecated::
            This method is not used by the ProdMCP runtime and lacks the
            before↔after pairing invariant. Use :func:`build_middleware_chain`
            to wrap handlers correctly.
        """
        import warnings
        warnings.warn(
            "MiddlewareManager.execute_after() is deprecated and unused by the runtime. "
            "Use build_middleware_chain() for proper before/after pairing guarantees.",
            DeprecationWarning,
            stacklevel=2,
        )
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

    Guarantees the before↔after pairing invariant: every middleware whose
    ``before`` completes successfully will always have its ``after`` called,
    even if a later ``before`` hook, the handler itself, or an earlier
    ``after`` hook raises an exception.

    Returns an async callable that preserves the original handler's signature.
    """
    import functools
    import inspect as _inspect

    chain = middleware_manager.get_chain(entity_middleware)

    @functools.wraps(handler)
    async def wrapped(*args: Any, **kwargs: Any) -> Any:
        # D4 fix: accept *args so the actual calling convention matches what
        # __signature__ advertises.  The old `**kwargs`-only definition would raise
        # TypeError on positional calls despite the signature appearing to accept them.
        context = MiddlewareContext(
            entity_type=entity_type,
            entity_name=entity_name,
            args=args,
            kwargs=kwargs,
        )

        # --- Phase 1: before hooks ---
        # Track each middleware that successfully completes its before() so
        # we can guarantee its after() is always called (Bug P3-2 fix).
        # If before[N] raises: run after[N-1..0] (those that entered) then re-raise.
        entered: list[Middleware] = []
        before_error: Exception | None = None

        for mw in chain:
            try:
                await mw.before(context)
                entered.append(mw)
            except Exception as exc:  # noqa: BLE001
                before_error = exc
                context.error = exc
                break

        if before_error is not None:
            # Run paired after-hooks for all that successfully entered.
            for mw in reversed(entered):
                try:
                    await mw.after(context)
                except Exception:  # noqa: BLE001
                    pass  # suppress; don't mask the original before-error
            raise before_error

        # Update kwargs in case middleware modified them
        kwargs = context.kwargs

        # --- Phase 2: handler ---
        try:
            if _inspect.iscoroutinefunction(handler):
                result = await handler(*args, **kwargs)
            else:
                result = handler(*args, **kwargs)
            context.result = result
        except Exception as exc:  # noqa: BLE001
            context.error = exc
            # D1 fix: suppress individual after-hook errors in the handler-failure
            # cleanup path — identical to Phase 1 cleanup and Phase 3 success path.
            # B4 fixed Phase 3 but Phase 2 was missed: if after() raises here, the
            # remaining middlewares' after() hooks are silently never called.
            for mw in reversed(entered):
                try:
                    await mw.after(context)
                except Exception:  # noqa: BLE001
                    pass  # suppress; don't mask the original handler error
            raise

        # --- Phase 3: after hooks (success path) ---
        # B4 fix: suppress individual after-hook errors to uphold the pairing
        # invariant: every middleware whose before() completed must have its
        # after() called, even if an earlier after() in the reversed chain raised.
        # Errors are logged as warnings so they're not silently swallowed.
        for mw in reversed(entered):
            try:
                await mw.after(context)
            except Exception as _after_exc:  # noqa: BLE001
                logger.warning(
                    "Middleware %s.after() raised in success path (suppressed to "
                    "preserve pairing invariant): %s",
                    type(mw).__name__,
                    _after_exc,
                    exc_info=True,
                )

        return context.result

    # Copy the original function's signature so FastMCP can inspect parameters
    wrapped.__signature__ = _inspect.signature(handler)
    return wrapped
