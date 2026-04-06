"""Bug 8 regression test: Pydantic body param named 'request' broken in wrapped handler."""
import pytest
from pydantic import BaseModel


class ChatRequest(BaseModel):
    message: str


# ── helper: build a minimal FastAPI app via _add_api_route without full ProdMCP init ──

def _make_fastapi_with_route(app):
    """Call _add_api_route for each registry route, finalize pending first."""
    from fastapi import FastAPI
    from prodmcp.router import _add_api_route

    # Must finalize so security schemes (e.g. bearerAuth) are auto-registered
    # before _add_api_route reads security_config and calls _build_handler.
    app._finalize_pending()

    fa = FastAPI(title="test")
    for meta in app._registry.get("api", {}).values():
        _add_api_route(fa, app, meta)
    return fa


# ── Tests ──────────────────────────────────────────────────────────────────────

class TestBug8PydanticBodyParamRequest:
    """Pydantic body parameter named 'request' must not be treated as query param."""

    def test_named_request_with_input_schema(self):
        """POST handler `request: ChatRequest` with @app.common(input_schema=...) returns 200."""
        from prodmcp import ProdMCP, Depends
        from starlette.testclient import TestClient

        def get_ctx():
            return "ctx_value"

        app = ProdMCP(title="test")

        @app.post("/chat")
        @app.common(input_schema=ChatRequest)
        async def chat(request: ChatRequest, ctx=Depends(get_ctx)):
            return {"echo": request.message}

        fa = _make_fastapi_with_route(app)
        client = TestClient(fa, raise_server_exceptions=False)

        resp = client.post(
            "/chat",
            json={"message": "hello"},
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code in (200, 201), f"Expected 2xx, got {resp.status_code}: {resp.json()}"
        assert resp.json().get("echo") == "hello"

    def test_named_request_no_depends(self):
        """POST handler with only `request: ChatRequest` + input_schema triggers wrapping."""
        from prodmcp import ProdMCP
        from starlette.testclient import TestClient

        app = ProdMCP(title="test")

        @app.post("/chat")
        @app.common(input_schema=ChatRequest)
        async def chat(request: ChatRequest):
            return {"echo": request.message}

        fa = _make_fastapi_with_route(app)
        client = TestClient(fa, raise_server_exceptions=False)

        resp = client.post(
            "/chat",
            json={"message": "world"},
        )
        assert resp.status_code in (200, 201), f"Expected 2xx, got {resp.status_code}: {resp.json()}"
        assert resp.json().get("echo") == "world"

    def test_body_param_other_name(self):
        """Sanity check: body param named 'body' (not 'request') must also work."""
        from prodmcp import ProdMCP
        from starlette.testclient import TestClient

        app = ProdMCP(title="test")

        @app.post("/chat")
        @app.common(input_schema=ChatRequest)
        async def chat(body: ChatRequest):
            return {"echo": body.message}

        fa = _make_fastapi_with_route(app)
        client = TestClient(fa, raise_server_exceptions=False)

        resp = client.post(
            "/chat",
            json={"message": "world"},
        )
        assert resp.status_code in (200, 201), f"Expected 2xx, got {resp.status_code}: {resp.json()}"
        assert resp.json().get("echo") == "world"

    def test_missing_required_field_returns_422(self):
        """Missing required body field should return a 4xx error, not 200."""
        from prodmcp import ProdMCP
        from starlette.testclient import TestClient

        app = ProdMCP(title="test")

        @app.post("/chat")
        @app.common(input_schema=ChatRequest)
        async def chat(request: ChatRequest):
            return {"echo": request.message}

        fa = _make_fastapi_with_route(app)
        client = TestClient(fa, raise_server_exceptions=False)

        resp = client.post("/chat", json={})  # missing 'message'
        assert resp.status_code in (400, 422), f"Expected 4xx, got {resp.status_code}: {resp.json()}"
        assert resp.status_code != 200

    def test_named_request_was_not_treated_as_query_param(self):
        """Regression: the 422 loc=['query','request'] bug must not recur."""
        from prodmcp import ProdMCP
        from starlette.testclient import TestClient

        app = ProdMCP(title="test")

        @app.post("/chat")
        @app.common(input_schema=ChatRequest)
        async def chat(request: ChatRequest):
            return {"echo": request.message}

        fa = _make_fastapi_with_route(app)
        client = TestClient(fa, raise_server_exceptions=False)

        resp = client.post("/chat", json={"message": "hi"})
        # Before the fix this returned 422 with loc=["query","request"]
        assert resp.status_code in (200, 201), (
            f"Got {resp.status_code} — if loc=['query','request'] the Bug 8 regression recurred: {resp.json()}"
        )
        assert resp.json().get("echo") == "hi"
