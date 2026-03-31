"""Tests for the unified router: REST + MCP on a single server."""

import pytest

try:
    from fastapi.testclient import TestClient
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

from pydantic import BaseModel
from prodmcp.app import ProdMCP

pytestmark = pytest.mark.skipif(not HAS_FASTAPI, reason="FastAPI not installed")


class ItemOut(BaseModel):
    id: int
    name: str
    price: float


class ItemIn(BaseModel):
    name: str
    price: float


def _build_app() -> ProdMCP:
    """Build a ProdMCP app with both API routes and MCP tools."""
    from unittest.mock import MagicMock

    app = ProdMCP("UnifiedTest", version="1.0.0")
    app._mcp = MagicMock()

    # Pure API routes
    @app.get("/health", tags=["system"])
    def health():
        return {"status": "ok"}

    @app.get("/items", tags=["items"], response_model=list[ItemOut])
    def list_items():
        return [
            {"id": 1, "name": "Widget", "price": 9.99},
            {"id": 2, "name": "Gadget", "price": 29.99},
        ]

    @app.get("/items/{item_id}", response_model=ItemOut, tags=["items"])
    def get_item(item_id: int):
        return {"id": item_id, "name": "Widget", "price": 9.99}

    @app.post("/items", response_model=ItemOut, status_code=201, tags=["items"])
    def create_item(payload: ItemIn):
        return {"id": 3, "name": payload.name, "price": payload.price}

    @app.delete("/items/{item_id}", status_code=204, tags=["items"])
    def delete_item(item_id: int):
        return None

    # Pure MCP tool
    @app.tool(name="calculate", description="Add two numbers")
    def calculate(a: int, b: int) -> int:
        return a + b

    # Stacked: MCP + API
    @app.tool(name="weather", description="Get weather for a city")
    @app.get("/weather/{city}", tags=["weather"])
    def get_weather(city: str) -> dict:
        return {"city": city, "temp": 22.5}

    return app


class TestUnifiedRouterCreation:
    def test_creates_fastapi_app(self):
        from prodmcp.router import create_unified_app
        app = _build_app()
        fastapi_app = create_unified_app(app)
        assert fastapi_app is not None
        assert fastapi_app.title == "UnifiedTest"

    def test_api_routes_registered(self):
        from prodmcp.router import create_unified_app
        app = _build_app()
        fastapi_app = create_unified_app(app)
        paths = [r.path for r in fastapi_app.routes if hasattr(r, "path")]
        assert "/health" in paths
        assert "/items" in paths
        assert "/items/{item_id}" in paths
        assert "/weather/{city}" in paths


class TestUnifiedRouterHTTPCalls:
    def _client(self):
        from prodmcp.router import create_unified_app
        app = _build_app()
        fastapi_app = create_unified_app(app)
        return TestClient(fastapi_app)

    def test_get_health(self):
        client = self._client()
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    def test_get_items(self):
        client = self._client()
        resp = client.get("/items")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["name"] == "Widget"

    def test_get_item_by_id(self):
        client = self._client()
        resp = client.get("/items/42")
        assert resp.status_code == 200
        assert resp.json()["id"] == 42

    def test_create_item(self):
        client = self._client()
        resp = client.post("/items", json={"name": "NewItem", "price": 15.50})
        assert resp.status_code == 201
        assert resp.json()["name"] == "NewItem"

    def test_get_weather_stacked(self):
        """A stacked handler (tool + get) should be callable via HTTP."""
        client = self._client()
        resp = client.get("/weather/London")
        assert resp.status_code == 200
        assert resp.json()["city"] == "London"


class TestListApiRoutes:
    def test_list_api_routes_returns_all(self):
        app = _build_app()
        routes = app.list_api_routes()
        assert "/health:GET" in routes
        assert "/items:GET" in routes
        assert "/items:POST" in routes
        assert "/items/{item_id}:GET" in routes
        assert "/items/{item_id}:DELETE" in routes
        assert "/weather/{city}:GET" in routes
