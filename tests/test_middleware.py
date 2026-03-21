"""Tests for the middleware system."""

import pytest

from prodmcp.middleware import (
    LoggingMiddleware,
    Middleware,
    MiddlewareContext,
    MiddlewareManager,
    build_middleware_chain,
)


# ── Test Middleware Implementations ────────────────────────────────────


class TrackingMiddleware(Middleware):
    """Middleware that records calls for testing."""

    def __init__(self):
        self.before_calls: list[str] = []
        self.after_calls: list[str] = []

    async def before(self, context: MiddlewareContext) -> None:
        self.before_calls.append(context.entity_name)

    async def after(self, context: MiddlewareContext) -> None:
        self.after_calls.append(context.entity_name)


class ModifyingMiddleware(Middleware):
    """Middleware that modifies kwargs."""

    async def before(self, context: MiddlewareContext) -> None:
        context.kwargs["injected"] = True

    async def after(self, context: MiddlewareContext) -> None:
        pass


# ── MiddlewareManager ──────────────────────────────────────────────────


class TestMiddlewareManager:
    def test_add_instance(self):
        mgr = MiddlewareManager()
        mw = TrackingMiddleware()
        mgr.add(mw, name="tracker")
        chain = mgr.get_chain()
        assert mw in chain

    def test_add_class(self):
        mgr = MiddlewareManager()
        mgr.add(LoggingMiddleware)
        chain = mgr.get_chain()
        assert len(chain) == 1
        assert isinstance(chain[0], LoggingMiddleware)

    def test_entity_middleware(self):
        mgr = MiddlewareManager()
        tracker = TrackingMiddleware()
        mgr.register_named("tracker", tracker)
        chain = mgr.get_chain(["tracker"])
        assert tracker in chain

    @pytest.mark.asyncio
    async def test_before_after_order(self):
        mgr = MiddlewareManager()
        mw1 = TrackingMiddleware()
        mw2 = TrackingMiddleware()
        mgr.add(mw1, name="first")
        mgr.add(mw2, name="second")

        chain = mgr.get_chain()
        ctx = MiddlewareContext(entity_type="tool", entity_name="test_tool")

        await mgr.execute_before(chain, ctx)
        assert mw1.before_calls == ["test_tool"]
        assert mw2.before_calls == ["test_tool"]

        ctx.result = 42
        await mgr.execute_after(chain, ctx)
        # After runs in reverse
        assert mw2.after_calls == ["test_tool"]
        assert mw1.after_calls == ["test_tool"]


# ── build_middleware_chain ─────────────────────────────────────────────


class TestBuildMiddlewareChain:
    @pytest.mark.asyncio
    async def test_wraps_handler(self):
        mgr = MiddlewareManager()
        tracker = TrackingMiddleware()
        mgr.add(tracker)

        def handler(x=1):
            return x * 2

        wrapped = build_middleware_chain(
            handler, mgr, None, "tool", "double"
        )
        result = await wrapped(x=5)
        assert result == 10
        assert tracker.before_calls == ["double"]
        assert tracker.after_calls == ["double"]

    @pytest.mark.asyncio
    async def test_async_handler(self):
        mgr = MiddlewareManager()
        tracker = TrackingMiddleware()
        mgr.add(tracker)

        async def handler(x=1):
            return x * 3

        wrapped = build_middleware_chain(
            handler, mgr, None, "tool", "triple"
        )
        result = await wrapped(x=5)
        assert result == 15

    @pytest.mark.asyncio
    async def test_middleware_modifies_kwargs(self):
        mgr = MiddlewareManager()
        mgr.add(ModifyingMiddleware())

        def handler(**kwargs):
            return kwargs

        wrapped = build_middleware_chain(
            handler, mgr, None, "tool", "test"
        )
        result = await wrapped(foo="bar")
        assert result.get("injected") is True
        assert result.get("foo") == "bar"

    @pytest.mark.asyncio
    async def test_error_propagation(self):
        mgr = MiddlewareManager()
        tracker = TrackingMiddleware()
        mgr.add(tracker)

        def handler():
            raise ValueError("boom")

        wrapped = build_middleware_chain(
            handler, mgr, None, "tool", "fail"
        )
        with pytest.raises(ValueError, match="boom"):
            await wrapped()
        # After hook should still run
        assert tracker.after_calls == ["fail"]
