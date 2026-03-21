"""Tests for the schema engine."""

import pytest
from pydantic import BaseModel

from prodmcp.exceptions import ProdMCPValidationError
from prodmcp.schemas import (
    extract_schema_ref,
    resolve_schema,
    validate_data,
)


# ── Fixtures ───────────────────────────────────────────────────────────


class UserInput(BaseModel):
    user_id: str
    name: str


class UserOutput(BaseModel):
    email: str
    active: bool = True


# ── resolve_schema ─────────────────────────────────────────────────────


class TestResolveSchema:
    def test_none(self):
        assert resolve_schema(None) is None

    def test_pydantic_model(self):
        schema = resolve_schema(UserInput)
        assert isinstance(schema, dict)
        assert schema["type"] == "object"
        assert "user_id" in schema["properties"]
        assert "name" in schema["properties"]

    def test_dict_passthrough(self):
        raw = {"type": "object", "properties": {"x": {"type": "string"}}}
        assert resolve_schema(raw) is raw

    def test_invalid_type_raises(self):
        with pytest.raises(TypeError):
            resolve_schema("invalid")


# ── validate_data ──────────────────────────────────────────────────────


class TestValidateData:
    def test_none_schema_skips(self):
        assert validate_data({"anything": True}, None) == {"anything": True}

    def test_pydantic_valid(self):
        result = validate_data(
            {"user_id": "123", "name": "Alice"}, UserInput, direction="input"
        )
        assert result["user_id"] == "123"
        assert result["name"] == "Alice"

    def test_pydantic_invalid(self):
        with pytest.raises(ProdMCPValidationError) as exc_info:
            validate_data({"user_id": 123}, UserInput, direction="input")
        assert "validation failed" in str(exc_info.value).lower()

    def test_json_schema_valid(self):
        schema = {
            "type": "object",
            "properties": {"x": {"type": "string"}},
            "required": ["x"],
        }
        result = validate_data({"x": "hello"}, schema, direction="input")
        assert result["x"] == "hello"

    def test_json_schema_missing_required(self):
        schema = {
            "type": "object",
            "properties": {"x": {"type": "string"}},
            "required": ["x"],
        }
        with pytest.raises(ProdMCPValidationError) as exc_info:
            validate_data({}, schema, direction="input")
        assert exc_info.value.errors[0]["loc"] == ["x"]

    def test_json_schema_type_mismatch(self):
        schema = {
            "type": "object",
            "properties": {"x": {"type": "integer"}},
            "required": ["x"],
        }
        with pytest.raises(ProdMCPValidationError):
            validate_data({"x": "not_int"}, schema, direction="input")

    def test_json_schema_not_object(self):
        schema = {"type": "object"}
        with pytest.raises(ProdMCPValidationError):
            validate_data("not_a_dict", schema, direction="input")


# ── extract_schema_ref ─────────────────────────────────────────────────


class TestExtractSchemaRef:
    def test_none(self):
        components: dict = {"schemas": {}}
        assert extract_schema_ref(None, components) is None

    def test_pydantic_model_creates_ref(self):
        components: dict = {"schemas": {}}
        ref = extract_schema_ref(UserInput, components)
        assert ref == {"$ref": "#/components/schemas/UserInput"}
        assert "UserInput" in components["schemas"]

    def test_dict_returns_inline(self):
        components: dict = {"schemas": {}}
        raw = {"type": "object", "properties": {"y": {"type": "number"}}}
        ref = extract_schema_ref(raw, components)
        assert ref is raw
        assert len(components["schemas"]) == 0
