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


# ── Regression: global hooks must fire for prompts and resources ────────


class TestMiddlewareOnPromptsAndResources:
    """Bug regression: _register_prompt() and _register_resource() previously
    called create_validated_handler() directly, completely bypassing
    build_middleware_chain().  Global ProdMCP middleware (LoggingMiddleware,
    custom hooks) was silently a no-op for prompts and resources.
    """

    def _tracking_middleware(self):
        """Create a fresh TrackingMiddleware instance."""
        return TrackingMiddleware()

    def test_global_middleware_fires_for_prompts(self):
        """LoggingMiddleware (and any global hook) must run when a prompt is called."""
        from unittest.mock import MagicMock
        from prodmcp.app import ProdMCP

        tracker = TrackingMiddleware()
        app = ProdMCP("T")
        app._mcp = MagicMock()
        app.add_middleware(tracker, name="tracker")

        @app.prompt(name="greet")
        def greet(name: str = "World") -> str:
            return f"Hello {name}"

        # Force finalization (normally called by run() / test_mcp_as_fastapi())
        app._finalize_pending()

        # The prompt handler registered with FastMCP should be wrapped.
        # We verify by inspecting that tracker.before_calls is populated
        # when the registered (wrapped) handler is called.
        import asyncio
        # Retrieve the wrapped fn from FastMCP's internal tool list via mcp mock
        # The simplest way: call through the MCP bridge
        fa = app.test_mcp_as_fastapi()
        try:
            from fastapi.testclient import TestClient
            client = TestClient(fa)
            resp = client.post("/prompts/greet", json={"name": "ProdMCP"})
            assert resp.status_code == 200
        except ImportError:
            pass  # FastAPI not installed — skip HTTP part

        # Tracker is the definitive check: before_calls must include 'greet'
        # We call the wrapped fn directly to avoid needing FastAPI
        import asyncio

        # Get the mcp.prompt call's registered handler
        # mcp.prompt(name=..., description=...)(wrapped) saves wrapped
        # MagicMock records this: app._mcp.prompt.return_value.call_args[0][0]
        prompt_decorator = app._mcp.prompt.return_value
        wrapped_handler = prompt_decorator.call_args[0][0]
        asyncio.run(wrapped_handler(name="Test"))
        assert "greet" in tracker.before_calls
        assert "greet" in tracker.after_calls

    def test_global_middleware_fires_for_resources(self):
        """Global ProdMCP middleware must run when a resource is read."""
        from unittest.mock import MagicMock
        from prodmcp.app import ProdMCP
        import asyncio

        tracker = TrackingMiddleware()
        app = ProdMCP("T")
        app._mcp = MagicMock()
        app.add_middleware(tracker, name="tracker")

        @app.resource(uri="data://items", name="item_db")
        def item_db() -> list:
            return ["a", "b"]

        app._finalize_pending()

        # Retrieve the wrapped resource handler from mcp mock
        resource_decorator = app._mcp.resource.return_value
        wrapped_handler = resource_decorator.call_args[0][0]
        asyncio.run(wrapped_handler())
        assert "item_db" in tracker.before_calls
        assert "item_db" in tracker.after_calls

    def test_tools_still_get_middleware(self):
        """Sanity check: tool middleware must still work after the refactor."""
        from unittest.mock import MagicMock
        from prodmcp.app import ProdMCP
        import asyncio

        tracker = TrackingMiddleware()
        app = ProdMCP("T")
        app._mcp = MagicMock()
        app.add_middleware(tracker, name="tracker")

        @app.tool(name="calc")
        def calc(x: int = 0) -> int:
            return x * 2

        app._finalize_pending()

        tool_decorator = app._mcp.tool.return_value
        wrapped_handler = tool_decorator.call_args[0][0]
        asyncio.run(wrapped_handler(x=5))
        assert "calc" in tracker.before_calls
        assert "calc" in tracker.after_calls

    def test_middleware_entity_type_is_correct(self):
        """Context.entity_type must be 'prompt' for prompts, 'resource' for resources."""
        from unittest.mock import MagicMock
        from prodmcp.app import ProdMCP
        from prodmcp.middleware import MiddlewareContext
        import asyncio

        captured_types: list[str] = []

        class TypeCapture(TrackingMiddleware):
            async def before(self, context: MiddlewareContext) -> None:
                await super().before(context)
                captured_types.append(context.entity_type)

        capture = TypeCapture()
        app = ProdMCP("T")
        app._mcp = MagicMock()
        app.add_middleware(capture)

        @app.prompt(name="p")
        def p() -> str: return "hi"

        @app.resource(uri="r://x", name="r")
        def r() -> list: return []

        app._finalize_pending()

        import asyncio
        for call in app._mcp.prompt.return_value.call_args_list:
            asyncio.run(call[0][0]())
        for call in app._mcp.resource.return_value.call_args_list:
            asyncio.run(call[0][0]())

        assert "prompt" in captured_types
        assert "resource" in captured_types
