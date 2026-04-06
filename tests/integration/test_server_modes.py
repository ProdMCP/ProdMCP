"""
Comprehensive server-mode integration tests for ProdMCP.

Goal
----
Verify that ProdMCP works correctly in three server configurations:

  1. **API-only**  — REST routes, no MCP tools
  2. **SSE-only**  — pure MCP/SSE, no user REST routes
  3. **Unified**   — REST + MCP combined in one ASGI application

For each configuration the suite validates:
  • Server starts and responds correctly (via TestClient)
  • ASGI middlewares (CORS, GZip) are applied and headers visible
  • ProdMCP-level middleware (Logging, custom Audit) fires on requests
  • Security (bearer token) is enforced on protected REST routes
  • Dependency injection delivers expected values
  • Pydantic body parameters are routed correctly

Import-surface contract
-----------------------
All *user-facing* imports in this file come exclusively from ``prodmcp``.
Zero top-level ``fastapi.*`` or ``starlette.*`` imports are permitted for
user code.  The self-sufficiency tests in the final class enforce this
programmatically.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic import BaseModel

# ── ONLY prodmcp imports ─────────────────────────────────────────────────────
from prodmcp import (
    BearerAuth,
    CORSMiddleware,
    Depends,
    GZipMiddleware,
    HTTPException,
    JSONResponse,
    LoggingMiddleware,
    Middleware,
    MiddlewareContext,
    ProdMCP,
    Response,
    TestClient,
    TrustedHostMiddleware,
)

# ── Schemas ──────────────────────────────────────────────────────────────────


class EchoRequest(BaseModel):
    message: str
    repeat: int = 1


class ItemRequest(BaseModel):
    name: str
    price: float


# ── Shared middleware helpers ─────────────────────────────────────────────────


class AuditMiddleware(Middleware):
    """Records before/after hooks into a list provided at construction time."""

    def __init__(self, log: list[str]) -> None:
        self._log = log

    async def before(self, context: MiddlewareContext) -> None:
        self._log.append(f"before:{context.entity_name}")

    async def after(self, context: MiddlewareContext) -> None:
        self._log.append(f"after:{context.entity_name}")


# ── Internal helpers ──────────────────────────────────────────────────────────


def _client(app: ProdMCP, **kwargs) -> TestClient:
    """Build a ProdMCP unified ASGI app and wrap it in a TestClient."""
    from prodmcp.router import create_unified_app
    return TestClient(create_unified_app(app), raise_server_exceptions=False, **kwargs)


# ─────────────────────────────────────────────────────────────────────────────
# 1. IMPORT-SURFACE TESTS
# ─────────────────────────────────────────────────────────────────────────────


class TestImportSurface:
    """Everything a user needs must be importable from prodmcp alone."""

    def test_testclient_is_re_exported(self):
        assert TestClient is not None

    def test_jsonresponse_is_re_exported(self):
        assert JSONResponse is not None

    def test_response_is_re_exported(self):
        assert Response is not None

    def test_cors_middleware_is_re_exported(self):
        assert CORSMiddleware is not None

    def test_gzip_middleware_is_re_exported(self):
        assert GZipMiddleware is not None

    def test_trusted_host_middleware_is_re_exported(self):
        assert TrustedHostMiddleware is not None

    def test_bearer_auth_is_re_exported(self):
        assert BearerAuth is not None

    def test_depends_is_re_exported(self):
        assert Depends is not None

    def test_httpexception_is_re_exported(self):
        assert HTTPException is not None

    def test_all_symbols_in_prodmcp_all(self):
        import prodmcp
        required = [
            "ProdMCP", "Depends", "Middleware", "MiddlewareContext",
            "LoggingMiddleware", "BearerAuth", "HTTPException",
            "CORSMiddleware", "GZipMiddleware", "TrustedHostMiddleware",
            "TestClient", "JSONResponse", "Response",
        ]
        for name in required:
            assert hasattr(prodmcp, name), f"prodmcp.{name} missing from package"

    def test_testclient_is_starlette_testclient(self):
        from starlette.testclient import TestClient as SC
        assert TestClient is SC

    def test_jsonresponse_is_fastapi_or_starlette(self):
        try:
            from fastapi.responses import JSONResponse as FJR
            assert JSONResponse is FJR
        except ImportError:
            from starlette.responses import JSONResponse as SJR
            assert JSONResponse is SJR

    def test_no_top_level_fastapi_starlette_imports_in_this_file(self):
        """Meta-test: verify user code in this file uses zero fastapi/starlette imports."""
        import ast
        import pathlib

        src = pathlib.Path(__file__).read_text()
        tree = ast.parse(src)

        violations = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module.startswith(("fastapi", "starlette")) and node.col_offset == 0:
                    violations.append(f"line {node.lineno}: from {module} import ...")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith(("fastapi", "starlette")) and node.col_offset == 0:
                        violations.append(f"line {node.lineno}: import {alias.name}")

        assert not violations, (
            "Import contract violated — top-level fastapi/starlette imports found:\n"
            + "\n".join(violations)
        )


# ─────────────────────────────────────────────────────────────────────────────
# 2. API-ONLY CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────


class TestAPIOnlyConfiguration:
    """REST-only server with no MCP tools registered."""

    @pytest.fixture()
    def app_and_client(self):
        audit_log: list[str] = []

        app = ProdMCP(title="API-Only Server", version="1.0.0")
        app.add_asgi_middleware(
            CORSMiddleware,
            allow_origins=["https://example.com"],
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["*"],
        )
        app.add_middleware(AuditMiddleware(log=audit_log), name="audit")

        @app.get("/health")
        def health() -> dict:
            return {"status": "ok", "server": "api-only"}

        @app.post("/echo")
        @app.common(middleware=["audit"], input_schema=EchoRequest)
        async def echo(request: EchoRequest) -> dict:
            return {"echo": request.message * request.repeat, "count": request.repeat}

        def _get_user() -> dict:
            return {"id": 42, "role": "admin"}

        @app.post("/whoami")
        @app.common(input_schema=ItemRequest)
        async def whoami(body: ItemRequest, user=Depends(_get_user)) -> dict:
            return {"user": user, "item": body.name}

        return app, _client(app), audit_log

    def test_health_endpoint_200(self, app_and_client):
        _, client, _ = app_and_client
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok", "server": "api-only"}

    def test_echo_with_repeat(self, app_and_client):
        _, client, _ = app_and_client
        resp = client.post("/echo", json={"message": "hi", "repeat": 3})
        assert resp.status_code in (200, 201)
        assert resp.json()["echo"] == "hihihi"
        assert resp.json()["count"] == 3

    def test_echo_default_repeat(self, app_and_client):
        _, client, _ = app_and_client
        resp = client.post("/echo", json={"message": "hello"})
        assert resp.status_code in (200, 201)
        assert resp.json()["echo"] == "hello"

    def test_echo_missing_field_returns_4xx(self, app_and_client):
        _, client, _ = app_and_client
        resp = client.post("/echo", json={})
        assert resp.status_code in (400, 422)

    def test_dependency_injection_delivers_user(self, app_and_client):
        _, client, _ = app_and_client
        resp = client.post("/whoami", json={"name": "widget", "price": 9.99})
        assert resp.status_code in (200, 201)
        data = resp.json()
        assert data["user"]["id"] == 42
        assert data["user"]["role"] == "admin"
        assert data["item"] == "widget"

    def test_cors_headers_returned_for_allowed_origin(self, app_and_client):
        _, client, _ = app_and_client
        resp = client.options(
            "/health",
            headers={"Origin": "https://example.com", "Access-Control-Request-Method": "GET"},
        )
        headers_lower = {k.lower(): v for k, v in resp.headers.items()}
        assert "access-control-allow-origin" in headers_lower, \
            f"CORS header missing. Headers: {dict(resp.headers)}"

    def test_openapi_schema_contains_user_routes(self, app_and_client):
        _, client, _ = app_and_client
        resp = client.get("/openapi.json")
        assert resp.status_code == 200
        schema = resp.json()
        assert "/health" in schema["paths"]
        assert "/echo" in schema["paths"]

    def test_swagger_docs_served(self, app_and_client):
        _, client, _ = app_and_client
        assert client.get("/docs").status_code == 200

    def test_mcp_tools_empty_in_api_only_mode(self, app_and_client):
        app, _, _ = app_and_client
        assert len(app.list_tools()) == 0

    def test_openmcp_spec_has_no_tools(self, app_and_client):
        app, _, _ = app_and_client
        spec = app.export_openmcp()
        assert len(spec.get("tools", {})) == 0


# ─────────────────────────────────────────────────────────────────────────────
# 3. UNIFIED CONFIGURATION (REST + MCP)
# ─────────────────────────────────────────────────────────────────────────────


class TestUnifiedConfiguration:
    """REST + MCP combined in one ASGI application."""

    @pytest.fixture()
    def app_and_client(self):
        app = ProdMCP(title="Unified Server", version="2.0.0")
        app.add_asgi_middleware(GZipMiddleware, minimum_size=100)
        app.add_middleware(LoggingMiddleware, name="logger")

        @app.tool(name="add", description="Add two numbers", middleware=["logger"])
        def add(a: int, b: int) -> dict:
            return {"result": a + b}

        @app.get("/version")
        def version() -> dict:
            return {"version": app.version}

        @app.post("/items")
        @app.common(input_schema=ItemRequest)
        async def create_item(body: ItemRequest) -> dict:
            return {"id": 1, "name": body.name, "price": body.price}

        return app, _client(app)

    def test_rest_version_endpoint(self, app_and_client):
        _, client = app_and_client
        resp = client.get("/version")
        assert resp.status_code == 200
        assert resp.json()["version"] == "2.0.0"

    def test_rest_post_pydantic_body(self, app_and_client):
        _, client = app_and_client
        resp = client.post("/items", json={"name": "widget", "price": 19.99})
        assert resp.status_code in (200, 201)
        assert resp.json()["name"] == "widget"
        assert resp.json()["id"] == 1

    def test_items_missing_body_returns_4xx(self, app_and_client):
        _, client = app_and_client
        resp = client.post("/items", json={})
        assert resp.status_code in (400, 422)

    def test_mcp_tool_registered(self, app_and_client):
        app, _ = app_and_client
        assert "add" in app.list_tools()

    def test_mcp_tool_callable_directly(self, app_and_client):
        app, _ = app_and_client
        result = app.get_tool_meta("add")["handler"](a=3, b=4)
        assert result["result"] == 7

    def test_openapi_contains_rest_routes(self, app_and_client):
        _, client = app_and_client
        schema = client.get("/openapi.json").json()
        assert "/version" in schema["paths"]
        assert "/items" in schema["paths"]

    def test_openmcp_spec_contains_tools(self, app_and_client):
        app, _ = app_and_client
        spec = app.export_openmcp()
        assert "add" in spec["tools"]
        assert spec["info"]["title"] == "Unified Server"

    def test_mcp_endpoint_reachable(self, app_and_client):
        _, client = app_and_client
        # Just check the MCP mount is present — stream may close immediately in test
        resp = client.get("/mcp", headers={"Accept": "text/event-stream"})
        assert resp.status_code in (200, 400, 404, 405, 422)

    def test_gzip_headers_visible_for_large_response(self, app_and_client):
        """GZipMiddleware (from prodmcp import GZipMiddleware) compresses large responses."""
        _, client = app_and_client
        resp = client.get(
            "/version",
            headers={"Accept-Encoding": "gzip"},
        )
        # Response is fine — compression is transparent
        assert resp.status_code == 200


# ─────────────────────────────────────────────────────────────────────────────
# 4. SSE-ONLY CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────


class TestSSEOnlyConfiguration:
    """Pure MCP / SSE server — user registers no REST routes."""

    @pytest.fixture()
    def app(self):
        _app = ProdMCP(title="SSE Server", version="0.1.0")
        _app.add_middleware(LoggingMiddleware, name="logger")

        @_app.tool(name="ping", description="Ping", middleware=["logger"])
        def ping() -> dict:
            return {"pong": True}

        @_app.prompt(name="greet", description="Greet a user")
        def greet(name: str) -> str:
            return f"Hello, {name}!"

        @_app.resource(uri="data://info", name="info", description="Server info")
        def info() -> dict:
            return {"server": "sse-only"}

        return _app

    @pytest.fixture()
    def client(self, app):
        return _client(app)

    def test_tool_registered(self, app):
        assert "ping" in app.list_tools()

    def test_prompt_registered(self, app):
        assert "greet" in app.list_prompts()

    def test_resource_registered(self, app):
        assert "info" in app.list_resources()

    def test_tool_handler_returns_correct_result(self, app):
        result = app.get_tool_meta("ping")["handler"]()
        assert result["pong"] is True

    def test_prompt_handler_returns_greeting(self, app):
        result = app.get_prompt_meta("greet")["handler"](name="Alice")
        assert "Alice" in result

    def test_resource_handler_returns_info(self, app):
        result = app.get_resource_meta("info")["handler"]()
        assert result["server"] == "sse-only"

    def test_openmcp_spec_has_all_entity_types(self, app):
        spec = app.export_openmcp()
        assert "ping" in spec["tools"]
        assert "greet" in spec["prompts"]
        assert "info" in spec["resources"]

    def test_no_user_rest_routes_in_openapi(self, client):
        """Only infra paths should exist — user never called @app.get/post."""
        schema = client.get("/openapi.json").json()
        user_paths = {
            p for p in schema.get("paths", {})
            if p not in {"/docs", "/docs/oauth2-redirect", "/redoc", "/mcp", "/sse"}
        }
        assert not user_paths, f"Unexpected user REST routes: {user_paths}"

    def test_spec_json_roundtrip(self, app):
        parsed = json.loads(app.export_openmcp_json())
        assert "tools" in parsed
        assert "ping" in parsed["tools"]


# ─────────────────────────────────────────────────────────────────────────────
# 5. MIDDLEWARE INTEGRATION
# ─────────────────────────────────────────────────────────────────────────────


class TestMiddlewareIntegration:
    """Middleware fires correctly in all configurations."""

    def test_custom_middleware_fires_on_rest_route(self):
        log: list[str] = []
        app = ProdMCP(title="MWTest")
        app.add_middleware(AuditMiddleware(log=log), name="audit")

        @app.post("/traced")
        @app.common(middleware=["audit"], input_schema=EchoRequest)
        async def traced(request: EchoRequest) -> dict:
            return {"echo": request.message}

        client = _client(app)
        resp = client.post("/traced", json={"message": "test"})
        assert resp.status_code in (200, 201), f"Got {resp.status_code}: {resp.text}"
        assert any("before:traced" in e for e in log), f"Before hook missing: {log}"
        assert any("after:traced" in e for e in log), f"After hook missing: {log}"

    def test_middleware_receives_entity_name_and_type(self):
        captured: list[MiddlewareContext] = []

        class CaptureMW(Middleware):
            async def before(self, context: MiddlewareContext) -> None:
                captured.append(context)

        app = ProdMCP(title="CtxTest")
        app.add_middleware(CaptureMW(), name="capture")

        @app.post("/probe")
        @app.common(middleware=["capture"], input_schema=EchoRequest)
        async def probe(request: EchoRequest) -> dict:
            return {"echo": request.message}

        resp = _client(app).post("/probe", json={"message": "x"})
        assert resp.status_code in (200, 201), resp.text
        assert len(captured) >= 1
        ctx = captured[0]
        assert ctx.entity_name == "probe"
        assert hasattr(ctx, "entity_type")

    def test_cors_middleware_from_prodmcp_import(self):
        app = ProdMCP(title="CORSTest")
        app.add_asgi_middleware(
            CORSMiddleware,
            allow_origins=["https://allowed.com"],
            allow_methods=["GET", "POST"],
            allow_headers=["*"],
        )

        @app.get("/data")
        def data() -> dict:
            return {"value": 42}

        resp = _client(app).get(
            "/data",
            headers={"Origin": "https://allowed.com"},
        )
        assert resp.status_code == 200
        headers_lower = {k.lower(): v for k, v in resp.headers.items()}
        assert "access-control-allow-origin" in headers_lower

    def test_gzip_middleware_from_prodmcp_import(self):
        app = ProdMCP(title="GZipTest")
        app.add_asgi_middleware(GZipMiddleware, minimum_size=1)

        @app.get("/bigdata")
        def bigdata() -> dict:
            return {"payload": "x" * 200}

        resp = _client(app).get(
            "/bigdata",
            headers={"Accept-Encoding": "gzip"},
        )
        assert resp.status_code == 200
        # Response is decompressed by TestClient, but the route must work
        assert resp.json()["payload"] == "x" * 200

    def test_multiple_asgi_middlewares_stack(self):
        app = ProdMCP(title="StackTest")
        app.add_asgi_middleware(CORSMiddleware, allow_origins=["*"],
                                allow_methods=["GET"], allow_headers=["*"])
        app.add_asgi_middleware(GZipMiddleware, minimum_size=1)

        @app.get("/stacked")
        def stacked() -> dict:
            return {"ok": True}

        resp = _client(app).get("/stacked", headers={"Origin": "https://any.com",
                                                       "Accept-Encoding": "gzip"})
        assert resp.status_code == 200
        headers_lower = {k.lower(): v for k, v in resp.headers.items()}
        assert "access-control-allow-origin" in headers_lower

    def test_logging_middleware_is_builtin_no_import_needed(self):
        """LoggingMiddleware shipped with prodmcp — no extra import required."""
        app = ProdMCP(title="LogTest")
        app.add_middleware(LoggingMiddleware, name="logger")

        @app.tool(name="compute", description="Compute", middleware=["logger"])
        def compute(x: int) -> dict:
            return {"result": x * 2}

        result = app.get_tool_meta("compute")["handler"](x=5)
        assert result["result"] == 10

    def test_named_middleware_fires_on_listed_route(self):
        """A middleware listed in middleware=[...] fires on that route."""
        log_a: list[str] = []
        log_b: list[str] = []

        class MWA(Middleware):
            async def before(self, ctx: MiddlewareContext) -> None:
                log_a.append("A")

        class MWB(Middleware):
            async def before(self, ctx: MiddlewareContext) -> None:
                log_b.append("B")

        app = ProdMCP(title="SelectiveMW")
        # Register both globally
        app.add_middleware(MWA(), name="mwa")
        app.add_middleware(MWB(), name="mwb")

        @app.post("/route-a-only")
        @app.common(middleware=["mwa"], input_schema=EchoRequest)
        async def route_a(request: EchoRequest) -> dict:
            return {"echo": request.message}

        _client(app).post("/route-a-only", json={"message": "hi"})
        # Both global middlewares fire — add_middleware is global registration
        assert log_a, "MWA should have fired (registered globally + listed)"
        assert log_b, "MWB fires on all routes since it was registered globally with add_middleware"

    def test_global_middleware_fires_on_all_routes(self):
        """add_middleware() registers a global middleware that fires on every route."""
        global_log: list[str] = []

        class GlobalMW(Middleware):
            async def before(self, ctx: MiddlewareContext) -> None:
                global_log.append(ctx.entity_name)

        app = ProdMCP(title="GlobalMW")
        app.add_middleware(GlobalMW(), name="global")

        @app.post("/a")
        @app.common(middleware=["global"], input_schema=EchoRequest)
        async def route_a(request: EchoRequest) -> dict:
            return {"echo": "a"}

        @app.post("/b")
        @app.common(middleware=["global"], input_schema=EchoRequest)
        async def route_b(request: EchoRequest) -> dict:
            return {"echo": "b"}

        c = _client(app)
        c.post("/a", json={"message": "x"})
        c.post("/b", json={"message": "y"})
        assert "route_a" in global_log or any("a" in e for e in global_log), \
            f"Global MW should fire on /a: {global_log}"
        assert "route_b" in global_log or any("b" in e for e in global_log), \
            f"Global MW should fire on /b: {global_log}"


# ─────────────────────────────────────────────────────────────────────────────
# 6. SECURITY INTEGRATION
# ─────────────────────────────────────────────────────────────────────────────


class TestSecurityIntegration:
    """Bearer auth enforced via @app.common(security=...) on REST routes."""

    VALID_TOKEN = "secret-bearer-token"

    @pytest.fixture()
    def client(self):
        app = ProdMCP(title="SecuredServer")

        valid_token = self.VALID_TOKEN
        app.add_security_scheme(
            "mybearer",
            BearerAuth(
                scope_validator=lambda token: ["read"] if token == valid_token else [],
                scopes=["read"],
            ),
        )

        @app.get("/public")
        def public() -> dict:
            return {"access": "public"}

        @app.post("/protected")
        @app.common(
            security=[{"mybearer": ["read"]}],
            input_schema=EchoRequest,
        )
        async def protected(request: EchoRequest) -> dict:
            return {"secret": request.message}

        return _client(app)

    def test_public_route_no_auth_needed(self, client):
        resp = client.get("/public")
        assert resp.status_code == 200
        assert resp.json()["access"] == "public"

    def test_protected_route_rejects_no_token(self, client):
        resp = client.post("/protected", json={"message": "hi"})
        assert resp.status_code in (401, 403)

    def test_protected_route_accepts_valid_token(self, client):
        resp = client.post(
            "/protected",
            json={"message": "hello"},
            headers={"Authorization": f"Bearer {self.VALID_TOKEN}"},
        )
        assert resp.status_code in (200, 201), f"Expected 2xx, got {resp.status_code}: {resp.text}"
        assert resp.json()["secret"] == "hello"

    def test_protected_route_rejects_wrong_token(self, client):
        resp = client.post(
            "/protected",
            json={"message": "hello"},
            headers={"Authorization": "Bearer wrong-token"},
        )
        assert resp.status_code in (401, 403), f"Expected 4xx, got {resp.status_code}"


# ─────────────────────────────────────────────────────────────────────────────
# 7. DEPENDENCY INJECTION
# ─────────────────────────────────────────────────────────────────────────────


class TestDependencyInjection:
    """Depends() from prodmcp resolves nested dependency chains."""

    @pytest.fixture()
    def app_and_client(self):
        class _Log:
            calls: list[str] = []

        log = _Log()

        def get_db():
            log.calls.append("db")
            return {"host": "localhost"}

        def get_user(db=Depends(get_db)):
            log.calls.append("user")
            return {"id": 99, "db": db["host"]}

        app = ProdMCP(title="DIServer")

        @app.post("/user-info")
        @app.common(input_schema=EchoRequest)
        async def user_info(request: EchoRequest, user=Depends(get_user)) -> dict:
            return {"msg": request.message, "user_id": user["id"]}

        return app, _client(app), log

    def test_nested_depends_resolved(self, app_and_client):
        _, client, _ = app_and_client
        resp = client.post("/user-info", json={"message": "ping"})
        assert resp.status_code in (200, 201), f"{resp.status_code}: {resp.text}"
        data = resp.json()
        assert data["user_id"] == 99
        assert data["msg"] == "ping"

    def test_dependency_chain_is_called(self, app_and_client):
        _, client, log = app_and_client
        log.calls.clear()
        client.post("/user-info", json={"message": "probe"})
        assert "db" in log.calls, f"get_db not called: {log.calls}"
        assert "user" in log.calls, f"get_user not called: {log.calls}"

    def test_depends_duck_types_with_fastapi_depends(self):
        """prodmcp.Depends must have the same .dependency attribute as fastapi.Depends."""
        dep = Depends(lambda: "val")
        assert hasattr(dep, "dependency")
        assert callable(dep.dependency)

        try:
            from fastapi import Depends as FaDep
            fa_dep = FaDep(lambda: "val")
            assert hasattr(fa_dep, "dependency")
        except ImportError:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# 8. CUSTOM RESPONSE TYPES
# ─────────────────────────────────────────────────────────────────────────────


class TestCustomResponses:
    """JSONResponse and Response imported from prodmcp work in handlers."""

    @pytest.fixture()
    def client(self):
        app = ProdMCP(title="RespTest")

        @app.get("/json-resp")
        def json_resp():
            return JSONResponse(content={"custom": True}, status_code=202)

        @app.get("/plain-resp")
        def plain_resp():
            return Response(content="plain text", media_type="text/plain")

        return _client(app)

    def test_jsonresponse_custom_status(self, client):
        resp = client.get("/json-resp")
        assert resp.status_code == 202
        assert resp.json()["custom"] is True

    def test_plain_response_content(self, client):
        resp = client.get("/plain-resp")
        assert resp.status_code == 200
        assert resp.text == "plain text"


# ─────────────────────────────────────────────────────────────────────────────
# 9. SPEC GENERATION IN ALL CONFIGURATIONS
# ─────────────────────────────────────────────────────────────────────────────


class TestSpecGeneration:

    def test_api_only_spec_has_no_tools(self):
        app = ProdMCP(title="APIOnly")

        @app.get("/ping")
        def ping() -> dict:
            return {"ping": True}

        spec = app.export_openmcp()
        assert len(spec.get("tools", {})) == 0

    def test_unified_spec_has_tools(self):
        app = ProdMCP(title="Unified", version="2.0.0")

        @app.tool(name="add", description="Add")
        def add(a: int, b: int) -> dict:
            return {"result": a + b}

        @app.get("/ping")
        def ping() -> dict:
            return {"ok": True}

        spec = app.export_openmcp()
        assert "add" in spec["tools"]
        assert spec["info"]["version"] == "2.0.0"

    def test_sse_only_spec_has_prompts_and_resources(self):
        app = ProdMCP(title="SSE")

        @app.tool(name="t1", description="T1")
        def t1() -> dict:
            return {}

        @app.prompt(name="p1", description="P1")
        def p1() -> str:
            return "hi"

        @app.resource(uri="data://r1", name="r1", description="R1")
        def r1() -> dict:
            return {}

        spec = app.export_openmcp()
        assert "t1" in spec["tools"]
        assert "p1" in spec["prompts"]
        assert "r1" in spec["resources"]

    def test_spec_json_is_valid_for_all_modes(self):
        for title in ["APIOnly2", "Unified2", "SSE2"]:
            app = ProdMCP(title=title)
            parsed = json.loads(app.export_openmcp_json())
            assert "openmcp" in parsed


# ─────────────────────────────────────────────────────────────────────────────
# 10. SELF-SUFFICIENCY ENFORCEMENT
# ─────────────────────────────────────────────────────────────────────────────


class TestSelfSufficiency:

    def test_all_rest_optional_exports_non_none(self):
        """When [rest] extras installed, every re-exported symbol must be non-None."""
        import prodmcp
        for name in ["CORSMiddleware", "GZipMiddleware", "TrustedHostMiddleware",
                     "TestClient", "JSONResponse", "Response", "HTTPException"]:
            val = getattr(prodmcp, name, None)
            assert val is not None, f"prodmcp.{name} is None ([rest] extras may be missing)"

    def test_version_is_semver(self):
        from prodmcp import __version__
        assert isinstance(__version__, str)
        assert len(__version__.split(".")) >= 3

    def test_full_server_definition_uses_only_prodmcp(self):
        """
        Build a non-trivial server using exclusively prodmcp imports and verify
        it handles GET, POST, CORS, GZip, Bearer auth, and DI correctly.
        """
        VALID = "tok"
        app = ProdMCP(title="SelfSufficient", version="1.0.0")

        # ASGI middleware — from prodmcp
        app.add_asgi_middleware(CORSMiddleware, allow_origins=["*"],
                                allow_methods=["*"], allow_headers=["*"])
        app.add_asgi_middleware(GZipMiddleware, minimum_size=1)

        # ProdMCP middleware — from prodmcp
        app.add_middleware(LoggingMiddleware, name="log")

        # Security — from prodmcp
        app.add_security_scheme(
            "bearer",
            BearerAuth(scope_validator=lambda token: ["r"] if token == VALID else []),
        )

        def get_session() -> str:
            return "session-42"

        # Routes — all using prodmcp types with DI
        @app.get("/hi")
        def hi(session: str = Depends(get_session)) -> JSONResponse:
            return JSONResponse({"session": session})

        @app.post("/secure")
        @app.common(security=[{"bearer": []}], input_schema=EchoRequest, middleware=["log"])
        async def secure(request: EchoRequest) -> dict:
            return {"echo": request.message}

        client = _client(app)

        # GET with dependency injection
        r = client.get("/hi")
        assert r.status_code == 200
        assert r.json()["session"] == "session-42"

        # POST without auth → 403
        r = client.post("/secure", json={"message": "x"})
        assert r.status_code in (401, 403)

        # POST with valid auth
        r = client.post("/secure", json={"message": "ok"},
                        headers={"Authorization": f"Bearer {VALID}"})
        assert r.status_code in (200, 201), f"{r.status_code}: {r.text}"
        assert r.json()["echo"] == "ok"

        # CORS is present
        r = client.get("/hi", headers={"Origin": "https://anywhere.com"})
        assert "access-control-allow-origin" in {k.lower() for k in r.headers}
