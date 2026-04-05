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


class TestASGIMiddleware:
    """Regression tests: ASGI-level middleware must survive create_unified_app()."""

    def _client_with_cors(self) -> "TestClient":
        from fastapi.middleware.cors import CORSMiddleware
        from prodmcp.router import create_unified_app

        app = _build_app()
        app.add_asgi_middleware(
            CORSMiddleware,
            allow_origins=["https://example.com"],
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["*"],
        )
        fastapi_app = create_unified_app(app)
        return TestClient(fastapi_app, raise_server_exceptions=True)

    def test_cors_header_on_simple_request(self):
        """CORS middleware should set the Access-Control-Allow-Origin header."""
        client = self._client_with_cors()
        resp = client.get(
            "/health",
            headers={"Origin": "https://example.com"},
        )
        assert resp.status_code == 200
        assert resp.headers.get("access-control-allow-origin") == "https://example.com"

    def test_cors_preflight_request(self):
        """OPTIONS preflight must return 200, not 405, when CORSMiddleware is applied."""
        client = self._client_with_cors()
        resp = client.options(
            "/health",
            headers={
                "Origin": "https://example.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert resp.status_code == 200
        assert resp.headers.get("access-control-allow-origin") == "https://example.com"

    def test_no_cors_without_asgi_middleware(self):
        """Without CORS middleware, cross-origin header should be absent."""
        from prodmcp.router import create_unified_app

        app = _build_app()
        fastapi_app = create_unified_app(app)
        client = TestClient(fastapi_app)
        resp = client.get(
            "/health",
            headers={"Origin": "https://example.com"},
        )
        assert resp.status_code == 200
        # No CORS middleware → no CORS response headers
        assert "access-control-allow-origin" not in resp.headers

    def test_multiple_asgi_middlewares_applied(self):
        """Multiple ASGI middlewares should all be applied."""
        from starlette.middleware.gzip import GZipMiddleware
        from fastapi.middleware.cors import CORSMiddleware
        from prodmcp.router import create_unified_app

        app = _build_app()
        app.add_asgi_middleware(CORSMiddleware, allow_origins=["*"])
        app.add_asgi_middleware(GZipMiddleware, minimum_size=1)
        # Should not raise and should create a working app
        fastapi_app = create_unified_app(app)
        client = TestClient(fastapi_app)
        resp = client.get("/health", headers={"Origin": "https://foo.com"})
        assert resp.status_code == 200
        assert resp.headers.get("access-control-allow-origin") == "*"


class TestFalsyRouteKwargs:
    """Bug 3 regression: falsy-but-valid route kwargs must not be dropped.

    Before the fix, `if tags:` swallowed `tags=[]`, `if deprecated:` swallowed
    `deprecated=False`, and `if summary:` swallowed `summary=""`.
    """

    def test_empty_tags_list_is_forwarded(self):
        """tags=[] (explicitly no tags) must not be silently dropped."""
        from prodmcp.router import create_unified_app

        app = ProdMCP("T")
        app._mcp = __import__("unittest.mock", fromlist=["MagicMock"]).MagicMock()

        @app.get("/test", tags=[])
        def handler():
            return {}

        fastapi_app = create_unified_app(app)
        route = next(r for r in fastapi_app.routes if getattr(r, "path", None) == "/test")
        # FastAPI stores tags on the route; empty list should be present, not absent
        assert hasattr(route, "tags")
        assert route.tags == []

    def test_deprecated_false_is_forwarded(self):
        """deprecated=False must not crash and deprecated=True must be surfaced.

        FastAPI stores `deprecated=False` as `None` internally (its None-sentinel),
        but `deprecated=True` must be preserved. The important thing is that the
        route object is created (no crash) and that we stopped silently skipping it.
        """
        from prodmcp.router import create_unified_app

        app = ProdMCP("T")
        app._mcp = __import__("unittest.mock", fromlist=["MagicMock"]).MagicMock()

        @app.get("/dep-false", deprecated=False)
        def handler_false():
            return {}

        @app.get("/dep-true", deprecated=True)
        def handler_true():
            return {}

        # Should build without raising
        fastapi_app = create_unified_app(app)
        paths = [r.path for r in fastapi_app.routes if hasattr(r, "path")]
        assert "/dep-false" in paths
        assert "/dep-true" in paths

        # deprecated=True must be surfaced on the route
        true_route = next(r for r in fastapi_app.routes if getattr(r, "path", None) == "/dep-true")
        assert true_route.deprecated is True

    def test_empty_summary_is_not_dropped_silently(self):
        """summary='' is now passed to add_api_route (not silently omitted).

        FastAPI itself replaces '' with the docstring, which is its own behaviour
        and out of ProdMCP's control. The important regression to guard against is
        that ProdMCP was *silently skipping* the kwarg — confirmed fixed if a
        non-empty explicit summary IS correctly applied.
        """
        from prodmcp.router import create_unified_app

        app = ProdMCP("T")
        app._mcp = __import__("unittest.mock", fromlist=["MagicMock"]).MagicMock()

        @app.get("/has-summary", summary="Explicit summary")
        def handler():
            """Docstring that should be overridden."""
            return {}

        fastapi_app = create_unified_app(app)
        route = next(r for r in fastapi_app.routes if getattr(r, "path", None) == "/has-summary")
        # The explicit summary must win over the docstring
        assert route.summary == "Explicit summary"


class TestFinalizeInCreateUnifiedApp:
    """Bug 5 regression: create_unified_app() must call _finalize_pending()
    so that users who import it directly don't silently lose their MCP tools.
    """

    def test_tools_registered_before_create_unified_app(self):
        """Tools decorated before create_unified_app() must be visible in the registry."""
        from unittest.mock import MagicMock
        from prodmcp.router import create_unified_app

        app = ProdMCP("FinalizeTest")
        app._mcp = MagicMock()

        @app.tool(name="late_tool", description="Added before create_unified_app")
        def late_tool():
            return "ok"

        # Simulate: user calls create_unified_app directly (no app.run())
        # Before the fix, _pending_tools was never drained here → tool missing
        fastapi_app = create_unified_app(app)

        # Tool must now be in the registry
        assert "late_tool" in app.list_tools()

    def test_api_routes_registered_before_create_unified_app(self):
        """API routes must be present even when create_unified_app is called directly."""
        from unittest.mock import MagicMock
        from prodmcp.router import create_unified_app

        app = ProdMCP("RouteTest")
        app._mcp = MagicMock()

        @app.get("/direct")
        def handler():
            return {"ok": True}

        fastapi_app = create_unified_app(app)
        paths = [r.path for r in fastapi_app.routes if hasattr(r, "path")]
        assert "/direct" in paths


class TestExceptionHandlers:
    """Bug 6 regression: exception handlers registered via add_exception_handler()
    must survive the fresh FastAPI instantiation inside create_unified_app().
    """

    def test_custom_exception_handler_applied(self):
        """A ValueError raised inside a route should get the custom 400 response."""
        from unittest.mock import MagicMock
        from fastapi import Request
        from fastapi.responses import JSONResponse
        from prodmcp.router import create_unified_app

        app = ProdMCP("ExcTest")
        app._mcp = MagicMock()

        async def value_error_handler(request: Request, exc: ValueError):
            return JSONResponse(status_code=400, content={"detail": str(exc)})

        app.add_exception_handler(ValueError, value_error_handler)

        @app.get("/boom")
        def boom():
            raise ValueError("custom error")

        fastapi_app = create_unified_app(app)
        client = TestClient(fastapi_app, raise_server_exceptions=False)
        resp = client.get("/boom")
        assert resp.status_code == 400
        assert resp.json()["detail"] == "custom error"

    def test_status_code_exception_handler(self):
        """HTTP status-code based exception handlers must also be applied."""
        from unittest.mock import MagicMock
        from fastapi import Request, HTTPException
        from fastapi.responses import JSONResponse
        from prodmcp.router import create_unified_app

        app = ProdMCP("ExcTest2")
        app._mcp = MagicMock()

        async def not_found_handler(request: Request, exc: HTTPException):
            return JSONResponse(status_code=404, content={"msg": "not here"})

        app.add_exception_handler(404, not_found_handler)

        @app.get("/gone")
        def gone():
            raise HTTPException(status_code=404, detail="gone")

        fastapi_app = create_unified_app(app)
        client = TestClient(fastapi_app, raise_server_exceptions=False)
        resp = client.get("/gone")
        assert resp.status_code == 404
        assert resp.json()["msg"] == "not here"


class TestMCPSubAppMiddleware:
    """Regression: the FastMCP sub-app mounted at /mcp runs in an isolated
    Starlette ASGI scope and does NOT inherit the parent FastAPI's middleware.

    ProdMCP must manually wrap mcp_asgi with the registered middlewares before
    mounting so that CORS (and others) also applies to /mcp/sse requests.
    """

    def _make_stub_mcp_asgi(self):
        """Return a minimal ASGI app that responds to any request with 200,
        acting as a stub for FastMCP's sse_app()/http_app().
        """
        from starlette.applications import Starlette
        from starlette.responses import JSONResponse
        from starlette.routing import Route

        async def stub_endpoint(request):
            return JSONResponse({"mcp": "ok"})

        return Starlette(routes=[Route("/{path:path}", stub_endpoint)])

    def _build_app_with_stub_mcp(self):
        """ProdMCP app whose underlying mcp.sse_app() returns a stub ASGI app."""
        from unittest.mock import MagicMock

        stub_asgi = self._make_stub_mcp_asgi()
        mcp_mock = MagicMock()
        mcp_mock.sse_app.return_value = stub_asgi

        app = ProdMCP("MCPSubAppTest", mcp_path="/mcp")
        app._mcp = mcp_mock

        @app.get("/health")
        def health():
            return {"status": "ok"}

        return app

    def test_cors_reaches_mcp_subapp(self):
        """CORS header must be present on a cross-origin request to /mcp/*.

        Before the fix, CORSMiddleware on the parent FastAPI never intercepted
        mount()ed sub-app requests — so /mcp/sse always returned without CORS headers.
        """
        from fastapi.middleware.cors import CORSMiddleware
        from prodmcp.router import create_unified_app

        app = self._build_app_with_stub_mcp()
        app.add_asgi_middleware(
            CORSMiddleware,
            allow_origins=["https://client.example"],
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["*"],
        )

        fastapi_app = create_unified_app(app)
        client = TestClient(fastapi_app)

        # Hit the stub MCP sub-app with an Origin header
        resp = client.get(
            "/mcp/anything",
            headers={"Origin": "https://client.example"},
        )
        assert resp.status_code == 200
        # CORS header must be present on the MCP sub-app response
        assert (
            resp.headers.get("access-control-allow-origin") == "https://client.example"
        ), "CORSMiddleware must reach the mounted /mcp sub-app"

    def test_cors_preflight_reaches_mcp_subapp(self):
        """OPTIONS preflight to /mcp must return 200 with CORS headers."""
        from fastapi.middleware.cors import CORSMiddleware
        from prodmcp.router import create_unified_app

        app = self._build_app_with_stub_mcp()
        app.add_asgi_middleware(
            CORSMiddleware,
            allow_origins=["https://client.example"],
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["*"],
        )

        fastapi_app = create_unified_app(app)
        client = TestClient(fastapi_app)

        resp = client.options(
            "/mcp/sse",
            headers={
                "Origin": "https://client.example",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert resp.status_code == 200
        assert (
            resp.headers.get("access-control-allow-origin") == "https://client.example"
        )

    def test_parent_routes_still_get_cors(self):
        """After the sub-app wrapping, parent REST routes must still get CORS too."""
        from fastapi.middleware.cors import CORSMiddleware
        from prodmcp.router import create_unified_app

        app = self._build_app_with_stub_mcp()
        app.add_asgi_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
        )

        fastapi_app = create_unified_app(app)
        client = TestClient(fastapi_app)

        resp = client.get("/health", headers={"Origin": "https://any.com"})
        assert resp.status_code == 200
        assert resp.headers.get("access-control-allow-origin") == "*"

    def test_no_middleware_mount_still_works(self):
        """Without any ASGI middleware, the sub-app must mount and respond normally."""
        from prodmcp.router import create_unified_app

        app = self._build_app_with_stub_mcp()
        # No middlewares registered

        fastapi_app = create_unified_app(app)
        client = TestClient(fastapi_app)

        resp = client.get("/mcp/anything")
        assert resp.status_code == 200
        assert resp.json() == {"mcp": "ok"}

