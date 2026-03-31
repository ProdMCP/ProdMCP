"""Tests for deferred registration and finalization.

The deferred registration pattern ensures @app.common() (which executes
last in Python's decorator order) can feed config into @app.tool() etc.
"""

import pytest
from pydantic import BaseModel

from prodmcp.app import ProdMCP


class SchemaA(BaseModel):
    a: str

class SchemaB(BaseModel):
    b: int


class TestDeferredRegistration:
    """MCP decorators should defer registration until finalization."""

    def test_pending_tools_populated(self):
        app = ProdMCP("T")

        @app.tool(name="deferred")
        def deferred():
            return 1

        # Should be in pending, not yet in registry
        assert len(app._pending_tools) == 1
        assert app._registry["tools"] == {}

    def test_finalization_moves_to_registry(self):
        app = ProdMCP("T")

        @app.tool(name="deferred")
        def deferred():
            return 1

        # Trigger finalization
        tools = app.list_tools()
        assert "deferred" in tools
        assert len(app._pending_tools) == 0

    def test_finalization_via_get_tool_meta(self):
        app = ProdMCP("T")

        @app.tool(name="lazy")
        def lazy():
            return 1

        meta = app.get_tool_meta("lazy")
        assert meta is not None
        assert meta["name"] == "lazy"

    def test_finalization_via_export_openmcp(self):
        app = ProdMCP("T")

        @app.tool(name="spec_tool")
        def spec_tool():
            return 1

        spec = app.export_openmcp()
        assert "spec_tool" in spec["tools"]

    def test_multiple_finalizations_work(self):
        """New decorators added after first finalization should still register."""
        app = ProdMCP("T")

        @app.tool(name="first")
        def first():
            return 1

        # First finalization
        assert "first" in app.list_tools()

        @app.tool(name="second")
        def second():
            return 2

        # Second finalization
        assert "second" in app.list_tools()
        assert "first" in app.list_tools()

    def test_prompt_deferred(self):
        app = ProdMCP("T")

        @app.prompt(name="deferred_prompt")
        def deferred_prompt():
            return "hello"

        assert len(app._pending_prompts) == 1
        assert "deferred_prompt" in app.list_prompts()
        assert len(app._pending_prompts) == 0

    def test_resource_deferred(self):
        app = ProdMCP("T")

        @app.resource(uri="data://test", name="deferred_res")
        def deferred_res():
            return []

        assert len(app._pending_resources) == 1
        assert "deferred_res" in app.list_resources()
        assert len(app._pending_resources) == 0


class TestDeferredWithCommon:
    """Common config should be available at finalization time."""

    def test_common_feeds_tool_via_deferred(self):
        app = ProdMCP("T")

        @app.common(input_schema=SchemaA, output_schema=SchemaB)
        @app.tool(name="merged")
        def merged(a: str) -> dict:
            return {"b": 1}

        # At this point @app.common has set __prodmcp_common__
        # and @app.tool is pending
        assert hasattr(merged, "__prodmcp_common__")
        assert len(app._pending_tools) == 1

        # Finalize
        meta = app.get_tool_meta("merged")
        assert meta["input_schema"] is SchemaA
        assert meta["output_schema"] is SchemaB

    def test_interleaved_decorators(self):
        """Interleaved tool and tool_with_common registrations."""
        app = ProdMCP("T")

        @app.tool(name="plain")
        def plain():
            return 1

        @app.common(input_schema=SchemaA)
        @app.tool(name="common_tool")
        def common_tool(a: str) -> str:
            return "ok"

        @app.tool(name="another_plain")
        def another_plain():
            return 2

        assert "plain" in app.list_tools()
        assert "common_tool" in app.list_tools()
        assert "another_plain" in app.list_tools()

        meta = app.get_tool_meta("common_tool")
        assert meta["input_schema"] is SchemaA

        meta_plain = app.get_tool_meta("plain")
        assert meta_plain["input_schema"] is None


class TestApiRoutesDontDefer:
    """API routes (@app.get etc.) register immediately (no pending queue)."""

    def test_get_registers_immediately(self):
        app = ProdMCP("T")

        @app.get("/test")
        def test_handler():
            return {}

        # Should be in registry immediately
        assert "/test:GET" in app._registry["api"]
        assert "/test:GET" in app.list_api_routes()
