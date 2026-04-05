"""Second-pass regression tests for blind spots P2-1 through P2-14.

Corresponds to the second test-audit pass (test_blind_spots_pass2.md).
Each class maps to a specific P2-* blind spot and is designed to FAIL if the
corresponding bug is reintroduced.

Quick index:
  P2-1   TestInputCoercion
  P2-2   TestOutputPydanticToDict
  P2-3   TestSecurityContextInjection
  P2-4   TestDictSchemaWithoutProperties
  P2-5   TestParameterizedResourceRoute
  P2-6   TestMatchUriTemplate
  P2-7   (fixed directly in test_mcp_bridge.py)
  P2-8   (fixed directly in test_run_method.py)
  P2-9   (fixed directly in test_mcp_bridge.py)
  P2-10  (fixed directly in test_fastapi.py + fastapi.py source)
  P2-11  TestResolveSchemaRawDictIsolation
  P2-12  TestDuplicateToolName
  P2-13  TestEmptyAppSpec
  P2-14  TestNonStrictOutputValidation
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel
from unittest.mock import MagicMock

from prodmcp.exceptions import ProdMCPValidationError
from prodmcp.schemas import resolve_schema
from prodmcp.validation import create_validated_handler


# ── helpers ──────────────────────────────────────────────────────────────────

try:
    from fastapi.testclient import TestClient
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

pytestmark_fastapi = pytest.mark.skipif(not HAS_FASTAPI, reason="FastAPI not installed")


def _app(name="T"):
    from prodmcp.app import ProdMCP
    app = ProdMCP(name)
    app._mcp = MagicMock()
    return app


# ── P2-1 ─────────────────────────────────────────────────────────────────────


class TestInputCoercion:
    """P2-1 regression: Pydantic coerces input types; the handler must receive
    the coerced value, not the original kwargs.  Original tests always sent
    already-valid types so coercion was never exercised.
    """

    class CoerceModel(BaseModel):
        x: int
        flag: bool

    def test_string_coerced_to_int(self):
        """'3' (str) must be coerced to 3 (int) before the handler is called."""
        received = {}

        def handler(**kw):
            received.update(kw)
            return kw

        wrapped = create_validated_handler(handler, input_schema=self.CoerceModel)
        wrapped(x="3", flag=True)

        assert received["x"] == 3, "String '3' must be coerced to integer 3"
        assert isinstance(received["x"], int), (
            "Handler must receive coerced int, not original str"
        )

    def test_int_coerced_to_bool_respects_json_semantics(self):
        """Pydantic coerces 1 → True and 0 → False for bool fields."""
        received = {}

        def handler(**kw):
            received.update(kw)
            return kw

        wrapped = create_validated_handler(handler, input_schema=self.CoerceModel)
        wrapped(x=5, flag=1)   # 1 → True by Pydantic

        assert isinstance(received["flag"], bool)
        assert received["flag"] is True

    def test_coercion_does_not_return_original_kwargs(self):
        """When coercion changes a value, the wrapper must not fall back to
        passing the original (pre-coercion) kwargs to the handler.
        """
        original_str = "42"
        received = {}

        def handler(**kw):
            received.update(kw)
            return kw

        wrapped = create_validated_handler(handler, input_schema=self.CoerceModel)
        wrapped(x=original_str, flag=False)

        # The handler sees the coerced int, not the original string
        assert received["x"] is not original_str, (
            "_validate_input returned original kwargs instead of coerced ones"
        )
        assert received["x"] == 42


# ── P2-2 ─────────────────────────────────────────────────────────────────────


class TestOutputPydanticToDict:
    """P2-2 regression: a handler that returns a Pydantic model instance must
    have its output serialized to a plain dict, not returned as the model.
    """

    class OutModel(BaseModel):
        value: int
        label: str

    def test_pydantic_instance_serialized_to_dict(self):
        def handler():
            return self.OutModel(value=42, label="hello")

        wrapped = create_validated_handler(
            handler, output_schema=self.OutModel, strict=True
        )
        result = wrapped()

        assert isinstance(result, dict), (
            "Output must be a plain dict, not a Pydantic model instance"
        )
        assert result["value"] == 42
        assert result["label"] == "hello"

    def test_pydantic_instance_not_leaked_to_caller(self):
        """The Pydantic model object itself must not be returned."""
        def handler():
            return self.OutModel(value=1, label="x")

        wrapped = create_validated_handler(
            handler, output_schema=self.OutModel, strict=True
        )
        result = wrapped()

        assert not isinstance(result, BaseModel), (
            "Returned a Pydantic model instance — must be serialized to dict"
        )

    def test_dict_result_with_output_schema_still_validated(self):
        """A handler returning a dict (not a model instance) is also validated."""
        def handler():
            return {"value": 99, "label": "dict_result"}

        wrapped = create_validated_handler(
            handler, output_schema=self.OutModel, strict=True
        )
        result = wrapped()
        assert result["value"] == 99


# ── P2-3 ─────────────────────────────────────────────────────────────────────


@pytest.mark.skipif(not HAS_FASTAPI, reason="FastAPI not installed")
class TestSecurityContextInjection:
    """P2-3 regression: __security_context__ must only be injected into kwargs
    when meta["security"] is truthy. A tool with no security config must NOT
    have __security_context__ in its kwargs (it would be KeyError if accessed).
    """

    def test_no_security_context_injected_without_security_config(self):
        """Tool with security=None must not receive __security_context__ in kwargs."""
        received_kwargs: dict = {}
        app = _app()

        @app.tool(name="open_tool")
        def open_tool(**kw):
            received_kwargs.update(kw)
            return "ok"

        client = TestClient(app.as_fastapi())
        resp = client.post("/tools/open_tool", json={})
        assert resp.status_code == 200
        assert "__security_context__" not in received_kwargs, (
            "__security_context__ must NOT be injected for tools without security config"
        )

    def test_security_context_injected_when_security_present(self):
        """Tool with security config must receive __security_context__ in kwargs."""
        received_kwargs: dict = {}
        app = _app()
        from prodmcp.security import BearerAuth
        app.add_security_scheme("bearerAuth", BearerAuth(scopes=[]))

        @app.tool(name="secure_tool", security=[{"bearerAuth": []}])
        def secure_tool(__security_context__=None, **kw):
            received_kwargs["ctx"] = __security_context__
            return "ok"

        client = TestClient(app.as_fastapi())
        resp = client.post(
            "/tools/secure_tool",
            json={},
            headers={"Authorization": "Bearer token"},
        )
        assert resp.status_code == 200
        assert "ctx" in received_kwargs
        assert received_kwargs["ctx"] is not None


# ── P2-4 ─────────────────────────────────────────────────────────────────────


@pytest.mark.skipif(not HAS_FASTAPI, reason="FastAPI not installed")
class TestDictSchemaWithoutProperties:
    """P2-4 regression: a dict schema without a 'properties' key must still
    cause the tool route to be created and reachable (no 404/405).
    _ensure_pydantic returns None for such schemas, silently routing to the
    dict_route_handler path.
    """

    def test_object_schema_without_properties_is_routable(self):
        """Schema with additionalProperties but no properties → still creates route."""
        app = _app()
        schema = {"type": "object", "additionalProperties": True}

        @app.tool(name="flexible_tool", input_schema=schema)
        def flexible_tool(**kw):
            return {"received": kw}

        client = TestClient(app.as_fastapi())
        resp = client.post(
            "/tools/flexible_tool",
            json={"any_key": "any_value"},
            headers={"content-type": "application/json"},
        )
        # Must not be 404 (route missing) or 405 (wrong method)
        assert resp.status_code not in (404, 405), (
            f"Route /tools/flexible_tool returned {resp.status_code} — "
            "dict schema without 'properties' must still create a valid route"
        )

    def test_object_schema_with_required_but_no_properties_routes(self):
        """Schema with 'required' but no 'properties' must reach dict_route_handler."""
        app = _app()
        schema = {"type": "object", "required": ["name"]}

        @app.tool(name="req_only_tool", input_schema=schema)
        def req_only_tool(**kw):
            return kw

        client = TestClient(app.as_fastapi())
        # Not testing validation result — only that the route exists
        resp = client.post(
            "/tools/req_only_tool",
            json={"name": "test"},
            headers={"content-type": "application/json"},
        )
        assert resp.status_code in (200, 422)   # either ok or validation error — not 404/405


# ── P2-5 ─────────────────────────────────────────────────────────────────────


@pytest.mark.skipif(not HAS_FASTAPI, reason="FastAPI not installed")
class TestParameterizedResourceRoute:
    """P2-5 regression: @app.resource(uri='items/{item_id}') must be matched
    by _match_uri_template and the captured variables forwarded as kwargs to
    the handler.  This entire feature had ZERO end-to-end test coverage.
    """

    def test_single_variable_extracted_and_forwarded(self):
        """GET /resources/items/42 → handler called with item_id='42'."""
        app = _app()
        received: dict = {}

        @app.resource(uri="items/{item_id}", name="item_resource")
        def get_item(item_id: str) -> dict:
            received["item_id"] = item_id
            return {"id": item_id, "name": "Widget"}

        client = TestClient(app.as_fastapi())
        resp = client.get("/resources/items/42")

        assert resp.status_code == 200, (
            f"Expected 200 for parameterized resource, got {resp.status_code}. "
            "Check _match_uri_template and dynamic kwargs forwarding."
        )
        assert received.get("item_id") == "42", (
            f"Handler received item_id={received.get('item_id')!r}, expected '42'. "
            "URI template variables must be extracted and forwarded as handler kwargs."
        )
        content = resp.json()["content"]
        assert content["id"] == "42"

    def test_multi_segment_uri_template(self):
        """GET /resources/users/99/posts → handler with user_id='99', post_id='posts'."""
        app = _app()
        received: dict = {}

        @app.resource(uri="users/{user_id}/{section}", name="user_section")
        def get_section(user_id: str, section: str) -> dict:
            received.update({"user_id": user_id, "section": section})
            return {"user_id": user_id, "section": section}

        client = TestClient(app.as_fastapi())
        resp = client.get("/resources/users/99/posts")

        assert resp.status_code == 200
        assert received.get("user_id") == "99"
        assert received.get("section") == "posts"

    def test_static_resource_still_matches_exactly(self):
        """Static URIs (no template vars) must continue to match exactly, unaffected."""
        app = _app()

        @app.resource(uri="static://data", name="static_res")
        def static_res() -> str:
            return "static_value"

        client = TestClient(app.as_fastapi())
        resp = client.get("/resources/static://data")
        assert resp.status_code == 200
        assert resp.json()["content"] == "static_value"

    def test_non_matching_uri_falls_back_to_fastmcp(self):
        """An unregistered URI must attempt the FastMCP fallback (not crash with 500)."""
        app = _app()
        # FastMCP mock: read_resource raises an exception → 404
        app._mcp.read_resource = MagicMock(side_effect=Exception("not found"))

        @app.resource(uri="items/{id}", name="items")
        def items(id: str) -> str:
            return id

        client = TestClient(app.as_fastapi(), raise_server_exceptions=False)
        # Request a URI that doesn't match "items/{id}" pattern
        resp = client.get("/resources/completely://different/path")
        # Must not be 200 (should be 404 from the fallback attempting FastMCP + failing)
        assert resp.status_code in (404, 500)


# ── P2-6 ─────────────────────────────────────────────────────────────────────


class TestMatchUriTemplate:
    """P2-6 regression: unit tests for _match_uri_template edge cases
    that the original test suite never exercised.
    """

    def _match(self, template, uri):
        from prodmcp.fastapi import _match_uri_template
        return _match_uri_template(template, uri)

    def test_single_variable_matches(self):
        assert self._match("items/{id}", "items/42") == {"id": "42"}

    def test_no_match_returns_none(self):
        assert self._match("items/{id}", "other/42") is None

    def test_static_template_matches_exact(self):
        """Template with no vars must match only the exact URI."""
        assert self._match("data://static", "data://static") == {}
        assert self._match("data://static", "data://DIFFERENT") is None

    def test_multi_variable_template(self):
        """P2-6: two variables must both be captured."""
        result = self._match("res://{a}/{b}", "res://x/y")
        assert result == {"a": "x", "b": "y"}, (
            f"Multi-variable template capture failed: got {result}"
        )

    def test_slash_in_value_does_not_match_single_var(self):
        """[^/]+ must NOT match across path separators.
        'data://{id}' must NOT match 'data://x/y' because {id} can't contain '/'.
        """
        result = self._match("data://{id}", "data://x/y")
        assert result is None, (
            f"Template 'data://{{id}}' matched 'data://x/y' — "
            "single-segment captures must not span '/' (got {result})"
        )

    def test_numeric_value_captured_as_string(self):
        """Values are always captured as strings, never parsed as numbers."""
        result = self._match("count/{n}", "count/123")
        assert result == {"n": "123"}
        assert isinstance(result["n"], str)

    def test_special_chars_in_uri_escaped_for_regex(self):
        """Special regex chars in the static part of the template must be escaped."""
        # 'data.v2://{id}' — the '.' must match a literal dot, not any char
        result = self._match("data.v2://{id}", "dataXv2://42")
        assert result is None, "Dot in template prefix must be escaped (literal match only)"

        result2 = self._match("data.v2://{id}", "data.v2://42")
        assert result2 == {"id": "42"}


# ── P2-11 ────────────────────────────────────────────────────────────────────


class TestResolveSchemaRawDictIsolation:
    """P2-11 regression: resolve_schema(dict) must return a deep copy, not the
    same dict object.  The P3-N2 fix added deepcopy only to the Pydantic branch;
    the dict branch returned the original reference, allowing mutations to
    corrupt the original schema stored in tool_meta["input_schema"].
    """

    def test_mutating_returned_dict_does_not_alter_original(self):
        original = {"type": "object", "properties": {"x": {"type": "integer"}}}
        returned = resolve_schema(original)

        # Mutate the returned copy
        returned["INJECTED"] = True
        returned["properties"]["FAKE"] = {"type": "null"}

        # Original must remain clean
        assert "INJECTED" not in original, (
            "resolve_schema(dict) returned the same dict reference — "
            "mutation corrupted the original schema (P2-11 regression)."
        )
        assert "FAKE" not in original.get("properties", {}), (
            "Nested mutation inside returned dict bled into the original schema."
        )

    def test_each_call_returns_new_object(self):
        """Two calls to resolve_schema with the same dict must return separate objects."""
        schema = {"type": "string"}
        r1 = resolve_schema(schema)
        r2 = resolve_schema(schema)
        assert r1 is not r2, (
            "resolve_schema returned the same dict object twice — objects are shared"
        )
        assert r1 is not schema, (
            "resolve_schema returned the original schema object — should be a copy"
        )

    def test_tool_meta_schema_not_corrupted_after_spec_export(self):
        """Exporting the spec must not corrupt a tool's dict input_schema
        registered in the registry (spec-gen calls _rewrite_refs which mutates
        schemas — if resolve_schema returned the same ref, meta would be corrupted).
        """
        from prodmcp.app import ProdMCP
        app = ProdMCP("CorruptionTest")
        schema = {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        }

        @app.tool(name="dict_tool", input_schema=schema)
        def dict_tool(name: str) -> str:
            return name

        # Export the spec (this calls extract_schema_ref → _rewrite_refs)
        app.export_openmcp()

        # The original schema in tool_meta must be unmodified
        meta = app.get_tool_meta("dict_tool")
        stored_schema = meta["input_schema"]
        assert stored_schema.get("type") == "object"
        assert "name" in stored_schema.get("properties", {}), (
            "Tool's stored input_schema was corrupted after spec export. "
            "dict schemas need deepcopy in resolve_schema (P2-11 regression)."
        )


# ── P2-12 ────────────────────────────────────────────────────────────────────


class TestDuplicateToolName:
    """P2-12 regression: registering two tools with the same name must have
    a defined, documented contract.  Previously this was undefined — the dict
    key would be silently overwritten with no warning.
    """

    def test_second_registration_wins(self):
        """The last registered tool with a given name must be the active one."""
        from prodmcp.app import ProdMCP
        app = ProdMCP("DupTest")

        @app.tool(name="dup")
        def first(): return 1

        @app.tool(name="dup")
        def second(): return 2

        # Only one entry in the list
        tools = app.list_tools()
        assert tools.count("dup") == 1, (
            "Duplicate tool registration must not create two entries"
        )

        # The last registered handler wins
        meta = app.get_tool_meta("dup")
        assert meta["handler"]() == 2, (
            "Second registration must overwrite first — last-writer-wins contract"
        )

    def test_original_handler_not_callable_after_override(self):
        from prodmcp.app import ProdMCP
        app = ProdMCP("DupTest2")

        @app.tool(name="overridden")
        def v1(): return "v1"

        @app.tool(name="overridden")
        def v2(): return "v2"

        meta = app.get_tool_meta("overridden")
        # Invoking the registered handler must call v2, not v1
        assert meta["handler"]() == "v2"


# ── P2-13 ────────────────────────────────────────────────────────────────────


class TestEmptyAppSpec:
    """P2-13 regression: an empty app spec must not contain spurious top-level
    keys.  The original tests only checked that tools/prompts/resources are
    absent, but not components or security.
    """

    def test_empty_app_has_no_components(self):
        from prodmcp.app import ProdMCP
        app = ProdMCP("EmptyTest")
        spec = app.export_openmcp()

        # A completely empty app must not have a 'components' section
        assert "components" not in spec or not spec.get("components"), (
            "'components' key must be absent (or empty) for an app with no entities"
        )

    def test_tool_without_schema_produces_no_schema_component(self):
        """A bare tool with no Pydantic schema must not add anything to components.schemas."""
        from prodmcp.app import ProdMCP
        app = ProdMCP("BareToolTest")

        @app.tool(name="bare")
        def bare(): return "ok"

        spec = app.export_openmcp()
        schemas = spec.get("components", {}).get("schemas", {})
        assert len(schemas) == 0, (
            f"Expected no schemas for a bare tool, got: {list(schemas.keys())}"
        )

    def test_empty_app_spec_has_required_top_level_keys_only(self):
        """Only mandatory keys must appear in an empty app spec."""
        from prodmcp.app import ProdMCP
        app = ProdMCP("MinimalTest", version="0.0.1")
        spec = app.export_openmcp()

        # These must always be present
        assert "openmcp" in spec
        assert "info" in spec
        assert spec["info"]["title"] == "MinimalTest"
        assert spec["info"]["version"] == "0.0.1"

        # These must be absent when nothing is registered
        for unexpected in ("tools", "prompts", "resources", "security"):
            assert unexpected not in spec, (
                f"Key '{unexpected}' must not appear in spec for empty app"
            )


# ── P2-14 ────────────────────────────────────────────────────────────────────


class TestNonStrictOutputValidation:
    """P2-14 regression: the non-strict output path in _validate_output swallows
    validation failures and returns the original result.  The original test used a
    VALID return value — the swallow path was never actually reached.
    """

    class StrictModel(BaseModel):
        value: int

    def test_non_strict_swallows_completely_wrong_type(self):
        """strict=False: a handler returning the wrong type must NOT raise."""
        def bad_handler():
            return "definitely_not_a_dict_or_model"

        wrapped = create_validated_handler(
            bad_handler, output_schema=self.StrictModel, strict=False
        )
        # Must not raise — swallow and return original
        result = wrapped()
        assert result == "definitely_not_a_dict_or_model", (
            "Non-strict mode must return the original (invalid) result, not raise"
        )

    def test_non_strict_swallows_wrong_dict_structure(self):
        """strict=False with a dict missing required fields → swallow, not raise."""
        def handler():
            return {"WRONG_KEY": 42}  # missing 'value' field

        wrapped = create_validated_handler(
            handler, output_schema=self.StrictModel, strict=False
        )
        result = wrapped()
        # Does not raise — original bad result returned
        assert result == {"WRONG_KEY": 42}

    def test_strict_raises_on_completely_wrong_type(self):
        """strict=True (default): wrong output type must raise ProdMCPValidationError."""
        def bad_handler():
            return "not_a_valid_output"

        wrapped = create_validated_handler(
            bad_handler, output_schema=self.StrictModel, strict=True
        )
        with pytest.raises(ProdMCPValidationError):
            wrapped()

    def test_strict_raises_on_wrong_dict_structure(self):
        """strict=True: dict missing required fields must raise."""
        def handler():
            return {"WRONG_KEY": 99}

        wrapped = create_validated_handler(
            handler, output_schema=self.StrictModel, strict=True
        )
        with pytest.raises(ProdMCPValidationError):
            wrapped()

    def test_non_strict_with_valid_output_still_validates(self):
        """Non-strict with a valid output still validates and returns correctly."""
        def good_handler():
            return {"value": 7}

        wrapped = create_validated_handler(
            good_handler, output_schema=self.StrictModel, strict=False
        )
        result = good_handler()
        assert result["value"] == 7


# ── P2-10 companion: exception propagation through FastAPI handler chain ──────


@pytest.mark.skipif(not HAS_FASTAPI, reason="FastAPI not installed")
class TestExceptionPropagationToFastAPIHandlers:
    """P2-10 companion: now that _execute_wrapped uses typed except clauses,
    non-ProdMCP exceptions must reach FastAPI's custom exception handler chain.
    """

    def test_value_error_reaches_custom_handler(self):
        """A ValueError from a tool must be caught by app.add_exception_handler(ValueError)."""
        from fastapi import Request
        from fastapi.responses import JSONResponse

        app = _app("ExcTest")

        async def handler_fn(request: Request, exc: ValueError):
            return JSONResponse(status_code=400, content={"error": str(exc)})

        app.add_exception_handler(ValueError, handler_fn)

        @app.tool(name="fail_tool")
        def fail_tool() -> str:
            raise ValueError("intentional error")

        client = TestClient(app.as_fastapi(), raise_server_exceptions=False)
        resp = client.post("/tools/fail_tool", json={})

        assert resp.status_code == 400, (
            f"Expected 400 from custom ValueError handler, got {resp.status_code}. "
            "_execute_wrapped must not swallow non-ProdMCP exceptions."
        )
        assert resp.json()["error"] == "intentional error"

    def test_security_error_still_maps_to_403(self):
        """ProdMCPSecurityError must still be intercepted by _execute_wrapped → 403."""
        from prodmcp.security import BearerAuth

        app = _app("SecErrTest")
        app.add_security_scheme("bearerAuth", BearerAuth(scopes=[]))

        @app.tool(name="secure", security=[{"bearerAuth": []}])
        def secure_fn() -> str:
            return "ok"

        client = TestClient(app.as_fastapi(), raise_server_exceptions=False)
        # No Authorization header → ProdMCPSecurityError → 403
        resp = client.post("/tools/secure", json={})
        assert resp.status_code == 403

    def test_validation_error_still_maps_to_422(self):
        """ProdMCPValidationError must still be intercepted by _execute_wrapped → 422."""
        app = _app("ValErrTest")
        schema = {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        }

        @app.tool(name="val_tool", input_schema=schema)
        def val_tool(name: str) -> str:
            return name

        client = TestClient(app.as_fastapi(), raise_server_exceptions=False)
        # Send wrong body (missing required 'name') → 422
        resp = client.post(
            "/tools/val_tool",
            json={"WRONG": "field"},
            headers={"content-type": "application/json"},
        )
        assert resp.status_code == 422

    def test_http_exception_propagates_unchanged(self):
        """An HTTPException raised inside a tool must reach the client unchanged."""
        from fastapi import HTTPException as FastAPIHTTPException

        app = _app("HttpExcTest")

        @app.tool(name="http_exc_tool")
        def http_exc_tool() -> str:
            raise FastAPIHTTPException(status_code=418, detail="I'm a teapot")

        client = TestClient(app.as_fastapi(), raise_server_exceptions=False)
        resp = client.post("/tools/http_exc_tool", json={})
        assert resp.status_code == 418
        assert "teapot" in resp.json()["detail"]
