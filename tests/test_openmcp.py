"""Tests for OpenMCP spec generation."""

import pytest
from pydantic import BaseModel

from prodmcp.app import ProdMCP
from prodmcp.openmcp import generate_spec, spec_to_json


# ── Fixtures ───────────────────────────────────────────────────────────


class UserInput(BaseModel):
    user_id: str


class UserOutput(BaseModel):
    name: str
    email: str


class TextInput(BaseModel):
    text: str


def _create_app_with_entities() -> ProdMCP:
    """Create a ProdMCP app with tools, prompts, and resources registered."""
    app = ProdMCP("TestServer", version="2.0.0")

    @app.tool(
        name="get_user",
        description="Get user by ID",
        input_schema=UserInput,
        output_schema=UserOutput,
        security=[{"type": "bearer", "scopes": ["user"]}],
    )
    def get_user(user_id: str) -> dict:
        return {"name": "Alice", "email": "alice@example.com"}

    @app.prompt(
        name="explain",
        description="Explain a topic",
        input_schema=TextInput,
    )
    def explain(text: str) -> str:
        return f"Explain: {text}"

    @app.resource(
        uri="data://users",
        name="user_db",
        description="User database",
        output_schema=UserOutput,
    )
    def user_db() -> list:
        return []

    return app


# ── Tests ──────────────────────────────────────────────────────────────


class TestGenerateSpec:
    def test_basic_structure(self):
        app = _create_app_with_entities()
        spec = app.export_openmcp()  # Use export_openmcp to trigger finalization

        assert spec["openmcp"] == "1.0.0"
        assert spec["info"]["title"] == "TestServer"
        assert spec["info"]["version"] == "2.0.0"

    def test_tools_section(self):
        app = _create_app_with_entities()
        spec = app.export_openmcp()

        assert "get_user" in spec["tools"]
        tool = spec["tools"]["get_user"]
        assert tool["description"] == "Get user by ID"
        assert "$ref" in tool["input"]
        assert "$ref" in tool["output"]

    def test_prompts_section(self):
        app = _create_app_with_entities()
        spec = app.export_openmcp()

        assert "explain" in spec["prompts"]
        prompt = spec["prompts"]["explain"]
        assert prompt["description"] == "Explain a topic"
        assert "$ref" in prompt["input"]

    def test_resources_section(self):
        app = _create_app_with_entities()
        spec = app.export_openmcp()

        assert "user_db" in spec["resources"]
        resource = spec["resources"]["user_db"]
        assert resource["uri"] == "data://users"
        assert "$ref" in resource["output"]

    def test_components_schemas(self):
        app = _create_app_with_entities()
        spec = app.export_openmcp()

        schemas = spec["components"]["schemas"]
        assert "UserInput" in schemas
        assert "UserOutput" in schemas
        assert "TextInput" in schemas

    def test_security_schemes(self):
        app = _create_app_with_entities()
        spec = app.export_openmcp()

        assert "securitySchemes" in spec["components"]
        assert "bearerAuth" in spec["components"]["securitySchemes"]

    def test_security_on_tool(self):
        app = _create_app_with_entities()
        spec = app.export_openmcp()

        tool = spec["tools"]["get_user"]
        assert "security" in tool
        assert tool["security"] == [{"bearerAuth": ["user"]}]


class TestSpecToJson:
    def test_serialization(self):
        app = _create_app_with_entities()
        spec = app.export_openmcp()
        json_str = app.export_openmcp_json()
        assert '"openmcp": "1.0.0"' in json_str
        assert '"TestServer"' in json_str


class TestEmptyApp:
    def test_empty_spec(self):
        app = ProdMCP("EmptyServer")
        spec = app.export_openmcp()
        assert spec["openmcp"] == "1.0.0"
        assert spec["info"]["title"] == "EmptyServer"
        # No tools/prompts/resources/components if nothing registered
        assert "tools" not in spec
        assert "prompts" not in spec
        assert "resources" not in spec
