"""Tests for the FastAPI bridge."""

import pytest
try:
    from fastapi.testclient import TestClient  # noqa: F401
    import httpx  # noqa: F401
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

from pydantic import BaseModel
from prodmcp.app import ProdMCP
from prodmcp.security import BearerAuth

pytestmark = pytest.mark.asyncio

class DummyInput(BaseModel):
    x: int

@pytest.mark.skipif(not HAS_FASTAPI, reason="FastAPI is not installed")
async def test_fastapi_routes():
    from unittest.mock import MagicMock
    app = ProdMCP("TestServer")
    app._mcp = MagicMock()

    @app.tool(input_schema=DummyInput)
    def my_tool(x: int) -> int:
        return x + 1

    @app.prompt(name="greet")
    def my_prompt() -> str:
        return "Hello"

    fastapi_app = app.as_fastapi()
    assert fastapi_app.title == "TestServer"

    routes = [r.path for r in fastapi_app.routes if hasattr(r, "path")]
    assert "/tools/my_tool" in routes
    assert "/prompts/greet" in routes
    assert "/resources/{mcp_uri:path}" in routes

@pytest.mark.skipif(not HAS_FASTAPI, reason="FastAPI is not installed")
async def test_fastapi_client():
    from unittest.mock import MagicMock
    from fastapi.testclient import TestClient
    app = ProdMCP("TestServer")
    app._mcp = MagicMock()

    @app.tool(input_schema=DummyInput)
    def my_tool(x: int) -> int:
        return x + 1

    fastapi_app = app.as_fastapi()
    client = TestClient(fastapi_app)

    response = client.post("/tools/my_tool", json={"x": 5})
    assert response.status_code == 200
    assert response.json() == 6

@pytest.mark.skipif(not HAS_FASTAPI, reason="FastAPI is not installed")
async def test_fastapi_comprehensive():
    from unittest.mock import MagicMock
    from fastapi.testclient import TestClient
    app = ProdMCP("ComprehensiveTestServer")
    app._mcp = MagicMock()

    # 4 tools
    @app.tool(name="tool_1", input_schema=DummyInput)
    def t1(x: int) -> int: return x
    @app.tool(name="tool_2", input_schema=DummyInput)
    def t2(x: int) -> int: return x * 2
    @app.tool(name="tool_3", input_schema=DummyInput)
    def t3(x: int) -> int: return x * 3
    @app.tool(name="tool_4", input_schema=DummyInput)
    def t4(x: int) -> int: return x * 4

    # 4 prompts
    @app.prompt(name="prompt_1")
    def p1() -> str: return "1"
    @app.prompt(name="prompt_2")
    def p2() -> str: return "2"
    @app.prompt(name="prompt_3")
    def p3() -> str: return "3"
    @app.prompt(name="prompt_4")
    def p4() -> str: return "4"

    # 2 resources
    @app.resource(uri="resource://1", name="res_1")
    def r1() -> str: return "res1"
    @app.resource(uri="resource://2", name="res_2")
    def r2() -> str: return "res2"

    fastapi_app = app.as_fastapi()
    client = TestClient(fastapi_app)

    routes = {r.path for r in fastapi_app.routes if hasattr(r, "path")}
    
    # Assert tools exist
    for i in range(1, 5):
        assert f"/tools/tool_{i}" in routes
        
    # Assert prompts exist
    for i in range(1, 5):
        assert f"/prompts/prompt_{i}" in routes

    # Assert resources exist
    assert "/resources/{mcp_uri:path}" in routes

    # Execute a tool
    resp = client.post("/tools/tool_3", json={"x": 5})
    assert resp.status_code == 200
    assert resp.json() == 15

    # Execute a prompt
    resp = client.post("/prompts/prompt_2")
    assert resp.status_code == 200
    assert resp.json() == "2"

@pytest.mark.skipif(not HAS_FASTAPI, reason="FastAPI is not installed")
async def test_fastapi_security_and_validation():
    from unittest.mock import MagicMock
    from fastapi.testclient import TestClient
    
    app = ProdMCP("SecurityTestServer")
    app._mcp = MagicMock()
    app.add_security_scheme("bearerAuth", BearerAuth(scopes=[]))

    class SecureInput(BaseModel):
        secret: str

    @app.tool(
        name="secure_tool",
        input_schema=SecureInput,
        security=[{"bearerAuth": []}]
    )
    def my_secure_tool(secret: str, __security_context__=None) -> str:
        return f"Access granted to {secret}"

    dict_schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string"}
        },
        "required": ["name"]
    }

    @app.tool(name="dict_tool", input_schema=dict_schema)
    async def my_dict_tool(name: str) -> str:
        return f"Hello {name}"
        
    @app.prompt(name="no_input_prompt")
    def no_input() -> str:
        return "Nothing"

    client = TestClient(app.as_fastapi())

    # 1. Missing security (403)
    resp = client.post("/tools/secure_tool", json={"secret": "abc"})
    assert resp.status_code == 403

    # 2. Valid security (200)
    resp = client.post(
        "/tools/secure_tool", 
        json={"secret": "abc"},
        headers={"Authorization": "Bearer secret_token"}
    )
    assert resp.status_code == 200
    assert "Access granted to abc" in resp.text

    # 3. Validation failure (422) - missing 'secret'
    resp = client.post(
        "/tools/secure_tool", 
        json={"wrong": "field"},
        headers={"Authorization": "Bearer secret_token"}
    )
    assert resp.status_code == 422

    # 4. Dict schema tool
    resp = client.post("/tools/dict_tool", json={"name": "ProdMCP"})
    assert resp.status_code == 200
    assert resp.json() == "Hello ProdMCP"

    # 5. Dict schema validation failure
    resp = client.post("/tools/dict_tool", json={"wrong": 123})
    assert resp.status_code == 422

    # 6. No input prompt
    resp = client.post("/prompts/no_input_prompt")
    assert resp.status_code == 200
    assert resp.json() == "Nothing"


@pytest.mark.skipif(not HAS_FASTAPI, reason="FastAPI is not installed")
async def test_asgi_middleware_in_as_fastapi():
    """Bug 2 regression: ASGI middleware registered via add_asgi_middleware() must
    be applied by create_fastapi_app() (as_fastapi()), not only by create_unified_app().
    """
    from unittest.mock import MagicMock
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.testclient import TestClient

    app = ProdMCP("MiddlewareTest")
    app._mcp = MagicMock()

    app.add_asgi_middleware(
        CORSMiddleware,
        allow_origins=["https://test.example"],
        allow_methods=["GET", "OPTIONS"],
        allow_headers=["*"],
    )

    @app.tool(name="ping")
    def ping() -> str:
        return "pong"

    fastapi_app = app.as_fastapi()
    client = TestClient(fastapi_app)

    # Simple cross-origin request should carry CORS header
    resp = client.post(
        "/tools/ping",
        json={},
        headers={"Origin": "https://test.example"},
    )
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == "https://test.example"


@pytest.mark.skipif(not HAS_FASTAPI, reason="FastAPI is not installed")
async def test_exception_handler_in_as_fastapi():
    """Bug 6 regression: exception handlers registered via add_exception_handler()
    must survive create_fastapi_app() (as_fastapi() path).
    """
    from unittest.mock import MagicMock
    from fastapi import Request
    from fastapi.responses import JSONResponse
    from fastapi.testclient import TestClient

    app = ProdMCP("ExcHandlerTest")
    app._mcp = MagicMock()

    async def value_error_handler(request: Request, exc: ValueError):
        return JSONResponse(status_code=400, content={"detail": "caught: " + str(exc)})

    app.add_exception_handler(ValueError, value_error_handler)

    @app.tool(name="raise_tool")
    def raise_tool() -> str:
        raise ValueError("test value error")

    fastapi_app = app.as_fastapi()
    client = TestClient(fastapi_app, raise_server_exceptions=False)
    resp = client.post("/tools/raise_tool", json={})
    # P2-10 fix: _execute_wrapped no longer swallows non-ProdMCP exceptions.
    # ValueError now propagates to FastAPI's handler chain → custom handler fires.
    assert resp.status_code == 400, (
        f"Expected 400 from custom ValueError handler, got {resp.status_code}. "
        "Check that _execute_wrapped doesn't catch non-ProdMCP exceptions."
    )
    assert resp.json()["detail"] == "caught: test value error"
