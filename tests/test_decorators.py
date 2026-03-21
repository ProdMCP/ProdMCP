"""Tests for the decorator layer and ProdMCP app registration."""

import pytest
from pydantic import BaseModel

from prodmcp.app import ProdMCP
from prodmcp.middleware import LoggingMiddleware


# ── Fixtures ───────────────────────────────────────────────────────────


class ItemInput(BaseModel):
    item_id: str
    quantity: int = 1


class ItemOutput(BaseModel):
    name: str
    price: float


# ── Tool Decorator ─────────────────────────────────────────────────────


class TestToolDecorator:
    def test_registers_tool(self):
        app = ProdMCP("Test")

        @app.tool(name="my_tool", description="A test tool")
        def my_tool():
            return "result"

        assert "my_tool" in app.list_tools()
        meta = app.get_tool_meta("my_tool")
        assert meta["description"] == "A test tool"

    def test_default_name_from_function(self):
        app = ProdMCP("Test")

        @app.tool()
        def calculate():
            return 42

        assert "calculate" in app.list_tools()

    def test_with_schemas(self):
        app = ProdMCP("Test")

        @app.tool(
            name="get_item",
            input_schema=ItemInput,
            output_schema=ItemOutput,
        )
        def get_item(item_id: str, quantity: int = 1) -> dict:
            return {"name": "Widget", "price": 9.99}

        meta = app.get_tool_meta("get_item")
        assert meta["input_schema"] is ItemInput
        assert meta["output_schema"] is ItemOutput

    def test_with_security(self):
        app = ProdMCP("Test")

        @app.tool(
            name="secure_tool",
            security=[{"type": "bearer", "scopes": ["admin"]}],
        )
        def secure_tool():
            return "secret"

        meta = app.get_tool_meta("secure_tool")
        assert len(meta["security"]) == 1
        assert meta["security"][0]["type"] == "bearer"

    def test_with_middleware(self):
        app = ProdMCP("Test")
        app.add_middleware(LoggingMiddleware, name="logging")

        @app.tool(name="logged_tool", middleware=["logging"])
        def logged_tool():
            return "logged"

        meta = app.get_tool_meta("logged_tool")
        assert "logging" in meta["middleware"]

    def test_preserves_original_function(self):
        app = ProdMCP("Test")

        @app.tool(name="pure")
        def pure_fn():
            """Original doc."""
            return 42

        # Decorator should return the original function
        assert pure_fn() == 42
        assert pure_fn.__doc__ == "Original doc."


# ── Prompt Decorator ───────────────────────────────────────────────────


class TestPromptDecorator:
    def test_registers_prompt(self):
        app = ProdMCP("Test")

        @app.prompt(name="my_prompt", description="A test prompt")
        def my_prompt(text: str) -> str:
            return f"Prompt: {text}"

        assert "my_prompt" in app.list_prompts()
        meta = app.get_prompt_meta("my_prompt")
        assert meta["description"] == "A test prompt"

    def test_with_input_schema(self):
        app = ProdMCP("Test")

        @app.prompt(name="schema_prompt", input_schema=ItemInput)
        def schema_prompt(item_id: str) -> str:
            return f"Tell me about {item_id}"

        meta = app.get_prompt_meta("schema_prompt")
        assert meta["input_schema"] is ItemInput


# ── Resource Decorator ─────────────────────────────────────────────────


class TestResourceDecorator:
    def test_registers_resource(self):
        app = ProdMCP("Test")

        @app.resource(uri="data://items", name="items")
        def items():
            return []

        assert "items" in app.list_resources()
        meta = app.get_resource_meta("items")
        assert meta["uri"] == "data://items"

    def test_default_uri(self):
        app = ProdMCP("Test")

        @app.resource(name="auto_uri")
        def auto_uri():
            return {}

        meta = app.get_resource_meta("auto_uri")
        assert meta["uri"] == "resource://auto_uri"

    def test_with_output_schema(self):
        app = ProdMCP("Test")

        @app.resource(
            uri="data://item_db",
            name="item_db",
            output_schema=ItemOutput,
        )
        def item_db():
            return []

        meta = app.get_resource_meta("item_db")
        assert meta["output_schema"] is ItemOutput


# ── Introspection ──────────────────────────────────────────────────────


class TestIntrospection:
    def test_list_all(self):
        app = ProdMCP("Test")

        @app.tool(name="t1")
        def t1():
            pass

        @app.tool(name="t2")
        def t2():
            pass

        @app.prompt(name="p1")
        def p1():
            pass

        @app.resource(uri="r://r1", name="r1")
        def r1():
            pass

        assert app.list_tools() == ["t1", "t2"]
        assert app.list_prompts() == ["p1"]
        assert app.list_resources() == ["r1"]
