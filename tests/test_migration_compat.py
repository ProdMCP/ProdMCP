"""Tests for drop-in migration compatibility.

Ensures that code written for FastAPI or FastMCP works unchanged
when the import is swapped to ProdMCP.
"""

import pytest

try:
    from fastapi.testclient import TestClient
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

from pydantic import BaseModel


# ── FastMCP Drop-in Compatibility ──────────────────────────────────────

class TestFastMCPDropIn:
    """Code written for FastMCP should work when imported as ProdMCP."""

    def test_import_alias(self):
        from prodmcp import ProdMCP as FastMCP
        mcp = FastMCP("TestServer")
        assert mcp.name == "TestServer"

    def test_tool_decorator(self):
        from prodmcp import ProdMCP as FastMCP
        mcp = FastMCP("TestServer")

        @mcp.tool()
        def get_weather(city: str) -> str:
            return f"Sunny in {city}"

        assert "get_weather" in mcp.list_tools()

    def test_resource_decorator(self):
        from prodmcp import ProdMCP as FastMCP
        mcp = FastMCP("TestServer")

        @mcp.resource("data://config")
        def get_config() -> str:
            return '{"key": "value"}'

        assert "get_config" in mcp.list_resources()

    def test_resource_decorator_with_uri(self):
        from prodmcp import ProdMCP as FastMCP
        mcp = FastMCP("TestServer")

        @mcp.resource("data://users")
        def users() -> str:
            return "[]"

        meta = mcp.get_resource_meta("users")
        assert meta["uri"] == "data://users"

    def test_prompt_decorator(self):
        from prodmcp import ProdMCP as FastMCP
        mcp = FastMCP("TestServer")

        @mcp.prompt()
        def greeting(name: str) -> str:
            return f"Hello {name}"

        assert "greeting" in mcp.list_prompts()

    def test_original_function_unchanged(self):
        from prodmcp import ProdMCP as FastMCP
        mcp = FastMCP("TestServer")

        @mcp.tool()
        def add(a: int, b: int) -> int:
            """Add two numbers."""
            return a + b

        # Function should still work directly
        assert add(2, 3) == 5
        assert add.__doc__ == "Add two numbers."

    def test_async_tool(self):
        import asyncio
        from prodmcp import ProdMCP as FastMCP
        mcp = FastMCP("TestServer")

        @mcp.tool()
        async def async_tool(x: int) -> int:
            return x * 2

        assert asyncio.iscoroutinefunction(async_tool)
        assert "async_tool" in mcp.list_tools()


# ── FastAPI Drop-in Compatibility ──────────────────────────────────────

class TestFastAPIDropIn:
    """Code written for FastAPI should work when imported as ProdMCP."""

    def test_import_alias(self):
        from prodmcp import ProdMCP as FastAPI
        app = FastAPI(title="TestAPI")
        assert app.name == "TestAPI"

    def test_httpexception_import(self):
        from prodmcp import HTTPException
        assert HTTPException is not None

    def test_depends_import(self):
        from prodmcp import Depends
        assert Depends is not None

    def test_get_decorator_exists(self):
        from prodmcp import ProdMCP as FastAPI
        app = FastAPI(title="T")
        assert callable(app.get)

    def test_post_decorator_exists(self):
        from prodmcp import ProdMCP as FastAPI
        app = FastAPI(title="T")
        assert callable(app.post)

    def test_put_decorator_exists(self):
        from prodmcp import ProdMCP as FastAPI
        app = FastAPI(title="T")
        assert callable(app.put)

    def test_delete_decorator_exists(self):
        from prodmcp import ProdMCP as FastAPI
        app = FastAPI(title="T")
        assert callable(app.delete)

    def test_patch_decorator_exists(self):
        from prodmcp import ProdMCP as FastAPI
        app = FastAPI(title="T")
        assert callable(app.patch)

    def test_full_fastapi_pattern(self):
        """A realistic FastAPI-style app should work with ProdMCP."""
        from prodmcp import ProdMCP as FastAPI, HTTPException

        app = FastAPI(title="UserService", version="1.0.0")

        class UserCreate(BaseModel):
            username: str
            email: str

        class UserResponse(BaseModel):
            id: int
            username: str
            email: str

        USERS = {1: {"id": 1, "username": "alice", "email": "a@b.com"}}

        @app.get("/users/{user_id}", response_model=UserResponse, tags=["users"])
        def get_user(user_id: int):
            if user_id not in USERS:
                raise HTTPException(status_code=404, detail="Not found")
            return USERS[user_id]

        @app.post("/users", response_model=UserResponse, status_code=201, tags=["users"])
        def create_user(payload: UserCreate):
            return {"id": 2, "username": payload.username, "email": payload.email}

        @app.delete("/users/{user_id}", status_code=204, tags=["users"])
        def delete_user(user_id: int):
            return None

        routes = app.list_api_routes()
        assert "/users/{user_id}:GET" in routes
        assert "/users:POST" in routes
        assert "/users/{user_id}:DELETE" in routes

    @pytest.mark.skipif(not HAS_FASTAPI, reason="FastAPI not installed")
    def test_fastapi_pattern_with_testclient(self):
        """A full FastAPI-style app should respond correctly via TestClient."""
        from prodmcp import ProdMCP as FastAPI
        from prodmcp.router import create_unified_app

        app = FastAPI(title="UserService", version="1.0.0")

        class UserOut(BaseModel):
            id: int
            name: str

        @app.get("/users/{user_id}", response_model=UserOut)
        def get_user(user_id: int):
            return {"id": user_id, "name": "Alice"}

        @app.get("/health")
        def health():
            return {"status": "ok"}

        fastapi_app = create_unified_app(app)
        client = TestClient(fastapi_app)

        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

        resp = client.get("/users/42")
        assert resp.status_code == 200
        assert resp.json()["id"] == 42


# ── Backward Compatibility with Current ProdMCP ───────────────────────

class TestProdMCPBackwardCompat:
    """Existing ProdMCP code must continue to work."""

    def test_tool_with_all_inline_params(self):
        from prodmcp import ProdMCP, LoggingMiddleware

        app = ProdMCP("Legacy")
        app.add_middleware(LoggingMiddleware, name="logging")

        class LInput(BaseModel):
            x: int

        class LOutput(BaseModel):
            result: int

        @app.tool(
            name="legacy_tool",
            description="Legacy",
            input_schema=LInput,
            output_schema=LOutput,
            security=[{"type": "bearer", "scopes": ["admin"]}],
            middleware=["logging"],
            tags={"legacy"},
            strict=True,
        )
        def legacy_tool(x: int) -> dict:
            return {"result": x * 2}

        meta = app.get_tool_meta("legacy_tool")
        assert meta["input_schema"] is LInput
        assert meta["output_schema"] is LOutput
        assert meta["tags"] == {"legacy"}
        assert "logging" in meta["middleware"]

    def test_as_fastapi_alias(self):
        """The old as_fastapi() method should still work."""
        from unittest.mock import MagicMock
        from prodmcp import ProdMCP
        app = ProdMCP("T")
        app._mcp = MagicMock()

        @app.tool(name="t")
        def t():
            return 1

        fa = app.as_fastapi()
        assert fa is not None

    def test_test_mcp_as_fastapi(self):
        """The new test_mcp_as_fastapi() method should work."""
        from unittest.mock import MagicMock
        from prodmcp import ProdMCP
        app = ProdMCP("T")
        app._mcp = MagicMock()

        @app.tool(name="t")
        def t():
            return 1

        fa = app.test_mcp_as_fastapi()
        assert fa is not None

    def test_export_openmcp(self):
        from prodmcp import ProdMCP

        app = ProdMCP("Legacy", version="1.0.0")

        @app.tool(name="t", description="D")
        def t():
            return 1

        spec = app.export_openmcp()
        assert spec["openmcp"] == "1.0.0"
        assert "t" in spec["tools"]

    def test_export_openmcp_json(self):
        import json
        from prodmcp import ProdMCP

        app = ProdMCP("Legacy")

        @app.tool(name="t")
        def t():
            return 1

        j = app.export_openmcp_json()
        parsed = json.loads(j)
        assert "tools" in parsed
