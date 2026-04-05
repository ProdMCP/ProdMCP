"""Tests for the MCP testing bridge (test_mcp_as_fastapi / as_fastapi).

These tests verify the functionality that auto-maps MCP entities
to REST routes for testing purposes:
  Tools   → POST /tools/{name}
  Prompts → POST /prompts/{name}
  Resources → GET /resources/{uri}
"""

import pytest

try:
    from fastapi.testclient import TestClient
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

from pydantic import BaseModel
from prodmcp.app import ProdMCP

pytestmark = pytest.mark.skipif(not HAS_FASTAPI, reason="FastAPI not installed")


class ItemInput(BaseModel):
    name: str
    price: float


class ItemOutput(BaseModel):
    id: int
    name: str
    price: float


class TestMCPBridgeRoutes:
    """test_mcp_as_fastapi() should create REST routes for MCP entities."""

    def _build_app(self):
        from unittest.mock import MagicMock
        app = ProdMCP("BridgeTest")
        app._mcp = MagicMock()
        return app

    def test_tool_creates_post_route(self):
        app = self._build_app()

        @app.tool(name="calc", input_schema=ItemInput)
        def calc(name: str, price: float) -> dict:
            return {"id": 1, "name": name, "price": price}

        fa = app.test_mcp_as_fastapi()
        routes = {r.path for r in fa.routes if hasattr(r, "path")}
        assert "/tools/calc" in routes

    def test_prompt_creates_post_route(self):
        app = self._build_app()

        @app.prompt(name="greet")
        def greet(name: str) -> str:
            return f"Hello {name}"

        fa = app.test_mcp_as_fastapi()
        routes = {r.path for r in fa.routes if hasattr(r, "path")}
        assert "/prompts/greet" in routes

    def test_resource_creates_get_route(self):
        app = self._build_app()

        @app.resource(uri="data://items", name="item_db")
        def item_db() -> str:
            return "[]"

        fa = app.test_mcp_as_fastapi()
        routes = {r.path for r in fa.routes if hasattr(r, "path")}
        assert "/resources/{mcp_uri:path}" in routes


class TestMCPBridgeHTTPCalls:
    """Verify actual HTTP calls through the bridge."""

    def _client(self):
        from unittest.mock import MagicMock
        app = ProdMCP("BridgeTest")
        app._mcp = MagicMock()

        @app.tool(name="add", input_schema=ItemInput)
        def add(name: str, price: float) -> dict:
            return {"id": 1, "name": name, "price": price * 2}

        @app.prompt(name="summarize")
        def summarize(text: str = "default") -> str:
            return f"Summary: {text}"

        @app.tool(name="multiply")
        def multiply(a: int = 1, b: int = 1) -> int:
            return a * b

        fa = app.test_mcp_as_fastapi()
        return TestClient(fa)

    def test_tool_execution(self):
        client = self._client()
        resp = client.post("/tools/add", json={"name": "Widget", "price": 5.0})
        assert resp.status_code == 200
        assert resp.json()["price"] == 10.0

    def test_prompt_execution(self):
        client = self._client()
        resp = client.post("/prompts/summarize", json={"text": "hello world"})
        assert resp.status_code == 200
        # P2-7 fix: assert exact content, not just a substring prefix.
        # "Summary:" in resp.json() would pass for any string starting with
        # "Summary:" — even a wrong result like "Summary: WRONG".
        assert resp.json() == "Summary: hello world"

    def test_tool_with_defaults(self):
        client = self._client()
        resp = client.post("/tools/multiply", json={"a": 3, "b": 7})
        assert resp.status_code == 200
        assert resp.json() == 21


class TestMCPBridgeBackwardCompat:
    """as_fastapi() should be an alias for test_mcp_as_fastapi()."""

    def test_alias_returns_same_app(self):
        from unittest.mock import MagicMock
        app = ProdMCP("T")
        app._mcp = MagicMock()

        @app.tool(name="t")
        def t():
            return 1

        fa1 = app.test_mcp_as_fastapi()
        fa2 = app.as_fastapi()
        # P2-9 fix: use isinstance instead of type(x).__name__ comparison.
        # Comparing class name strings passes even if the actual class differs
        # (e.g. a Starlette subclass named "FastAPI" would fool the old check).
        from fastapi import FastAPI as _FastAPI
        assert isinstance(fa1, _FastAPI)
        assert isinstance(fa2, _FastAPI)

    def test_bridge_app_has_title(self):
        from unittest.mock import MagicMock
        app = ProdMCP("MyBridge")
        app._mcp = MagicMock()

        fa = app.test_mcp_as_fastapi()
        assert fa.title == "MyBridge"
