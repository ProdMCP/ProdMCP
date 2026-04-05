"""Tests for Depends() evaluation and inspection."""


import pytest

from prodmcp import Depends, ProdMCP
from prodmcp.security import OAuth2PasswordBearer

try:
    from fastapi.testclient import TestClient
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False


@pytest.mark.skipif(not HAS_FASTAPI, reason="FastAPI is not installed")
def test_dependency_stripping_and_injection():
    from unittest.mock import MagicMock
    app = ProdMCP()
    app._mcp = MagicMock()
    oauth_scheme = OAuth2PasswordBearer(token_url="/auth")

    @app.tool()
    def my_secured_tool(
        x: int, token: str = Depends(oauth_scheme)
    ) -> str:
        return f"User passed {x} and token {token}"

    meta = app.get_tool_meta("my_secured_tool")
    assert meta is not None
    
    # 1. Inspect security schema generation
    sec_conf = meta["security"]
    assert len(sec_conf) == 1
    scheme_key = list(sec_conf[0].keys())[0]
    assert scheme_key.startswith("auto_oauth2_")

    # 3. Test execution via the internal wrapper 
    client = TestClient(app.as_fastapi())
    resp = client.post(
        "/tools/my_secured_tool",
        json={"x": 42},
        headers={"Authorization": "Bearer injected_token"}
    )
    assert resp.status_code == 200
    assert resp.json() == "User passed 42 and token injected_token"


@pytest.mark.skipif(not HAS_FASTAPI, reason="FastAPI is not installed")
def test_standard_dependency():
    from unittest.mock import MagicMock
    app = ProdMCP()
    app._mcp = MagicMock()

    def get_db():
        return "db_connection"

    @app.tool()
    def regular_tool(data: str, db: str = Depends(get_db)):
        return f"{data} uses {db}"

    # 3. Test execution via the internal wrapper 
    client = TestClient(app.as_fastapi())
    resp = client.post(
        "/tools/regular_tool",
        json={"data": "Test"}
    )
    assert resp.status_code == 200
    assert resp.json() == "Test uses db_connection"

