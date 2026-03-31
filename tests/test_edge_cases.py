"""Edge case and boundary condition tests.

These tests cover unusual scenarios that could occur in production use:
- Empty/None values
- Unicode and special characters
- Large numbers of registrations
- Conflicting names
- Decorator order variations
"""

import pytest
from pydantic import BaseModel

from prodmcp.app import ProdMCP


class EmptyModel(BaseModel):
    pass


class UnicodeModel(BaseModel):
    name: str
    emoji: str = "🚀"


# ── Edge cases: Constructor ────────────────────────────────────────────

class TestConstructorEdgeCases:
    def test_empty_string_name(self):
        app = ProdMCP("")
        assert app.name == ""

    def test_very_long_name(self):
        name = "A" * 10000
        app = ProdMCP(name)
        assert app.name == name

    def test_unicode_name(self):
        app = ProdMCP("サーバー🌍")
        assert app.name == "サーバー🌍"

    def test_title_empty_string_name_fallback(self):
        """Empty title should fall back to positional name."""
        app = ProdMCP("Fallback", title="")
        # Empty string is falsy, so positional name wins
        assert app.name == "Fallback"

    def test_extra_kwargs_passed_through(self):
        app = ProdMCP("T", custom_arg="hello")
        assert app._fastmcp_kwargs["custom_arg"] == "hello"


# ── Edge cases: Tool Registration ──────────────────────────────────────

class TestToolEdgeCases:
    def test_tool_with_empty_description(self):
        app = ProdMCP("T")

        @app.tool(name="t", description="")
        def t():
            return 1

        meta = app.get_tool_meta("t")
        assert meta["description"] == ""

    def test_tool_without_name_uses_function_name(self):
        app = ProdMCP("T")

        @app.tool()
        def my_fancy_function():
            return 1

        assert "my_fancy_function" in app.list_tools()

    def test_tool_with_unicode_name(self):
        app = ProdMCP("T")

        @app.tool(name="outil_météo")
        def weather():
            return "sunny"

        assert "outil_météo" in app.list_tools()

    def test_tool_with_no_return_annotation(self):
        app = ProdMCP("T")

        @app.tool(name="no_return")
        def no_return():
            pass

        assert "no_return" in app.list_tools()

    def test_tool_docstring_used_as_description(self):
        app = ProdMCP("T")

        @app.tool()
        def documented():
            """This is the tool description."""
            return 1

        meta = app.get_tool_meta("documented")
        assert meta["description"] == "This is the tool description."

    def test_tool_with_multiline_docstring(self):
        app = ProdMCP("T")

        @app.tool()
        def multi():
            """First line.

            More details here.
            """
            return 1

        meta = app.get_tool_meta("multi")
        assert "First line." in meta["description"]

    def test_registering_many_tools(self):
        """Register 100 tools to test scale."""
        app = ProdMCP("T")

        for i in range(100):
            @app.tool(name=f"tool_{i}")
            def handler(idx=i):
                return idx

        assert len(app.list_tools()) == 100

    def test_tool_handler_is_preserved(self):
        """The original function should be returned by the decorator."""
        app = ProdMCP("T")
        original_id = None

        @app.tool(name="preserved")
        def my_fn():
            return 42

        assert my_fn() == 42

    def test_lambda_like_handler(self):
        """Functions with no docstring should work."""
        app = ProdMCP("T")

        @app.tool(name="nodoc")
        def nodoc():
            return None

        meta = app.get_tool_meta("nodoc")
        assert meta["description"] == ""


# ── Edge cases: Prompt Registration ────────────────────────────────────

class TestPromptEdgeCases:
    def test_prompt_returns_empty_string(self):
        app = ProdMCP("T")

        @app.prompt(name="empty_prompt")
        def empty_prompt():
            return ""

        assert "empty_prompt" in app.list_prompts()

    def test_prompt_with_complex_return(self):
        app = ProdMCP("T")

        @app.prompt(name="complex")
        def complex_prompt(text: str, lang: str = "en"):
            return f"[{lang}] Analyze: {text}"

        assert "complex" in app.list_prompts()


# ── Edge cases: Resource Registration ──────────────────────────────────

class TestResourceEdgeCases:
    def test_resource_auto_uri(self):
        app = ProdMCP("T")

        @app.resource(name="auto")
        def auto():
            return []

        meta = app.get_resource_meta("auto")
        assert meta["uri"] == "resource://auto"

    def test_resource_with_complex_uri(self):
        app = ProdMCP("T")

        @app.resource(uri="https://api.example.com/v2/data?format=json", name="complex_uri")
        def complex_uri():
            return []

        meta = app.get_resource_meta("complex_uri")
        assert meta["uri"] == "https://api.example.com/v2/data?format=json"


# ── Edge cases: HTTP Methods ──────────────────────────────────────────

class TestHttpMethodEdgeCases:
    def test_deep_nested_path(self):
        app = ProdMCP("T")

        @app.get("/api/v2/users/{org_id}/teams/{team_id}/members/{member_id}")
        def deep():
            return {}

        key = "/api/v2/users/{org_id}/teams/{team_id}/members/{member_id}:GET"
        assert key in app.list_api_routes()

    def test_path_with_query_like_params(self):
        app = ProdMCP("T")

        @app.get("/search")
        def search(q: str = "", limit: int = 10):
            return []

        assert "/search:GET" in app.list_api_routes()

    def test_multiple_decorators_same_path_different_methods(self):
        app = ProdMCP("T")

        @app.get("/resource")
        def get_resource():
            return []

        @app.post("/resource")
        def create_resource():
            return {}

        @app.put("/resource")
        def update_resource():
            return {}

        routes = app.list_api_routes()
        assert "/resource:GET" in routes
        assert "/resource:POST" in routes
        assert "/resource:PUT" in routes

    def test_status_code_zero(self):
        """Edge case: explicit status_code=0."""
        app = ProdMCP("T")

        @app.get("/test", status_code=0)
        def handler():
            return {}

        meta = app._registry["api"]["/test:GET"]
        assert meta["status_code"] == 0

    def test_empty_tags_list(self):
        app = ProdMCP("T")

        @app.get("/test", tags=[])
        def handler():
            return {}

        meta = app._registry["api"]["/test:GET"]
        assert meta["tags"] == []

    def test_responses_dict(self):
        app = ProdMCP("T")

        @app.get("/test", responses={404: {"description": "Not found"}})
        def handler():
            return {}

        meta = app._registry["api"]["/test:GET"]
        assert 404 in meta["responses"]


# ── Edge cases: Common Decorator ───────────────────────────────────────

class TestCommonEdgeCases:
    def test_common_with_no_args(self):
        """@app.common() with no arguments should work (just no shared config)."""
        app = ProdMCP("T")

        @app.common()
        @app.tool(name="bare")
        def bare():
            return 1

        meta = app.get_tool_meta("bare")
        assert meta["input_schema"] is None
        assert meta["output_schema"] is None

    def test_common_without_tool_or_api(self):
        """@app.common() without any MCP/API decorator — just sets attributes."""
        app = ProdMCP("T")

        @app.common(input_schema=UnicodeModel)
        def standalone():
            return 1

        assert hasattr(standalone, "__prodmcp_common__")
        assert standalone.__prodmcp_common__["input_schema"] is UnicodeModel

    def test_common_does_not_affect_other_functions(self):
        """@app.common() on one function should not affect another."""
        app = ProdMCP("T")

        @app.common(input_schema=UnicodeModel)
        @app.tool(name="with_common")
        def fn1():
            return 1

        @app.tool(name="without_common")
        def fn2():
            return 2

        meta1 = app.get_tool_meta("with_common")
        meta2 = app.get_tool_meta("without_common")
        assert meta1["input_schema"] is UnicodeModel
        assert meta2["input_schema"] is None


# ── Edge cases: Stacking ──────────────────────────────────────────────

class TestStackingEdgeCases:
    def test_tool_on_multiple_http_methods(self):
        """One tool stacked with both GET and POST on different paths."""
        app = ProdMCP("T")

        @app.tool(name="item_ops", description="Item operations")
        @app.get("/items", tags=["items"])
        def item_list():
            return []

        @app.tool(name="item_create", description="Create item")
        @app.post("/items", tags=["items"])
        def item_create():
            return {}

        assert "item_ops" in app.list_tools()
        assert "item_create" in app.list_tools()
        assert "/items:GET" in app.list_api_routes()
        assert "/items:POST" in app.list_api_routes()

    def test_async_stacked_handler(self):
        """Async handlers should work with stacking."""
        import asyncio
        app = ProdMCP("T")

        @app.tool(name="async_calc")
        @app.post("/async-calc")
        async def async_calc(x: int) -> int:
            return x * 2

        assert asyncio.iscoroutinefunction(async_calc)
        assert "async_calc" in app.list_tools()
        assert "/async-calc:POST" in app.list_api_routes()
