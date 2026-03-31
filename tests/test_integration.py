"""End-to-end integration tests.

Tests the full flow: define entities → export OpenMCP spec → validate structure.
"""

import json

import pytest
from pydantic import BaseModel

from prodmcp import ProdMCP, LoggingMiddleware


# ── Schemas ────────────────────────────────────────────────────────────


class SearchInput(BaseModel):
    query: str
    limit: int = 10


class SearchResult(BaseModel):
    title: str
    score: float


class UserProfile(BaseModel):
    username: str
    email: str
    role: str = "viewer"


# ── Integration Tests ──────────────────────────────────────────────────


class TestFullFlow:
    def _build_app(self) -> ProdMCP:
        app = ProdMCP("IntegrationTest", version="3.0.0")
        app.add_middleware(LoggingMiddleware, name="logging")

        @app.tool(
            name="search",
            description="Search for items",
            input_schema=SearchInput,
            output_schema=SearchResult,
            security=[{"type": "bearer", "scopes": ["search"]}],
            middleware=["logging"],
            tags={"search", "data"},
        )
        def search(query: str, limit: int = 10) -> dict:
            return {"title": f"Result for {query}", "score": 0.95}

        @app.tool(
            name="get_profile",
            description="Get user profile",
            input_schema=UserProfile,
            output_schema=UserProfile,
            security=[{"type": "apikey"}],
        )
        def get_profile(username: str) -> dict:
            return {"username": username, "email": f"{username}@test.com", "role": "admin"}

        @app.prompt(
            name="analyze",
            description="Analyze search results",
            input_schema=SearchInput,
            output_schema=SearchResult,
        )
        def analyze(query: str, limit: int = 10) -> str:
            return f"Analyze results for: {query}"

        @app.resource(
            uri="data://profiles",
            name="profiles",
            description="All user profiles",
            output_schema=UserProfile,
        )
        def profiles() -> list:
            return [{"username": "alice", "email": "a@t.com", "role": "admin"}]

        return app

    def test_full_spec_generation(self):
        app = self._build_app()
        spec = app.export_openmcp()

        # Top-level structure
        assert spec["openmcp"] == "1.0.0"
        assert spec["info"]["title"] == "IntegrationTest"
        assert spec["info"]["version"] == "3.0.0"

        # Tools
        assert "search" in spec["tools"]
        assert "get_profile" in spec["tools"]
        search_tool = spec["tools"]["search"]
        assert search_tool["description"] == "Search for items"
        assert "$ref" in search_tool["input"]
        assert "$ref" in search_tool["output"]
        assert search_tool["middleware"] == ["logging"]
        assert "security" in search_tool

        # Prompts
        assert "analyze" in spec["prompts"]

        # Resources
        assert "profiles" in spec["resources"]
        assert spec["resources"]["profiles"]["uri"] == "data://profiles"

        # Components
        schemas = spec["components"]["schemas"]
        assert "SearchInput" in schemas
        assert "SearchResult" in schemas
        assert "UserProfile" in schemas

        # Security schemes
        sec_schemes = spec["components"]["securitySchemes"]
        assert "bearerAuth" in sec_schemes
        # apiKey scheme gets auto-generated names like apiKeyAuth_header_X-API-Key
        assert any(k.startswith("apiKeyAuth") for k in sec_schemes)

    def test_spec_json_roundtrip(self):
        app = self._build_app()
        json_str = app.export_openmcp_json(indent=2)
        parsed = json.loads(json_str)
        assert parsed["openmcp"] == "1.0.0"
        assert "tools" in parsed

    def test_registry_integrity(self):
        app = self._build_app()
        assert len(app.list_tools()) == 2
        assert len(app.list_prompts()) == 1
        assert len(app.list_resources()) == 1

    def test_tool_handler_preserved(self):
        app = self._build_app()
        meta = app.get_tool_meta("search")
        handler = meta["handler"]
        # Original handler should still work
        result = handler(query="test", limit=5)
        assert result["title"] == "Result for test"

    def test_schema_deduplication(self):
        """Shared schemas (e.g. UserProfile used in tool + resource)
        should appear only once in components.schemas."""
        app = self._build_app()
        spec = app.export_openmcp()
        schemas = spec["components"]["schemas"]
        # UserProfile appears in both get_profile tool and profiles resource
        # but should only be in schemas once
        user_profile_count = sum(
            1 for name in schemas if name == "UserProfile"
        )
        assert user_profile_count == 1


class TestMultipleSecuritySchemes:
    def test_or_security(self):
        """Tool with multiple security options should list them all."""
        app = ProdMCP("SecTest")

        @app.tool(
            name="multi_auth",
            security=[
                {"type": "bearer", "scopes": ["user"]},
                {"type": "apikey"},
            ],
        )
        def multi_auth():
            return "ok"

        spec = app.export_openmcp()
        tool_sec = spec["tools"]["multi_auth"]["security"]
        assert len(tool_sec) == 2
