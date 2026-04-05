"""Regression tests for blind spots in the ProdMCP test suite.

Each test class maps to one or more blind-spot (BS-*) items from the audit.
These tests are specifically designed to FAIL if the corresponding bug is
reintroduced — they use data and assertions that the original tests
conveniently avoided.

Quick index:
  BS-1 / BS-15  TestScopeValidatorEnforcement
  BS-2 / BS-3   TestSecuritySpecContent
  BS-4          TestAndSemanticsInSecurityRequirements
  BS-5          TestCustomAuthErrorMessage
  BS-6          TestEmptyKwargsValidation
  BS-7          TestBeforeHookFailurePairing
  BS-8          TestJsonSchemaArrayAndScalarValidation
  BS-9          TestResolveSchemaIsolation
  BS-12         TestApiKeyHeaderCaseInsensitive
  BS-14         TestMultilineDocstringExactSummary
  BS-16         TestCommonSecurityShorthandFormat
"""

from __future__ import annotations

import asyncio

import pytest
from pydantic import BaseModel

from prodmcp.exceptions import ProdMCPSecurityError, ProdMCPValidationError
from prodmcp.schemas import resolve_schema, validate_data
from prodmcp.security import (
    BearerAuth,
    SecurityContext,
    SecurityManager,
)
from prodmcp.security.api_key import APIKeyHeader
from prodmcp.validation import create_validated_handler


# ── BS-1 / BS-15 ──────────────────────────────────────────────────────────────


class TestScopeValidatorEnforcement:
    """BS-1 / BS-15 regression.

    The original test asserted ``sec.scopes == scheme.scopes`` — exactly the
    Bug 4 tautology (declared scopes == granted scopes).  These tests verify
    that ``scope_validator`` is actually called and that its return value (not
    the declared list) determines the granted scopes.
    """

    def test_scope_validator_return_overrides_declared_scopes(self):
        """scope_validator result must replace the declared scopes list."""
        def validator(token: str) -> list[str]:
            # Token carries only "read", not "admin"
            return ["read"]

        scheme = BearerAuth(scopes=["read", "admin"], scope_validator=validator)
        ctx = {"headers": {"authorization": "Bearer mytoken"}}
        sec = scheme.extract(ctx)

        # Validator said ["read"] — that's what the SecurityContext must carry
        assert sec.scopes == ["read"]
        # "admin" was declared but the token didn't grant it
        assert "admin" not in sec.scopes

    def test_scope_validator_can_grant_undeclared_scopes(self):
        """scope_validator return is taken verbatim — not filtered by declared scopes."""
        def validator(token: str) -> list[str]:
            return ["root", "god_mode"]  # not in declared scopes

        scheme = BearerAuth(scopes=["read"], scope_validator=validator)
        ctx = {"headers": {"authorization": "Bearer supertoken"}}
        sec = scheme.extract(ctx)

        assert "root" in sec.scopes
        assert "god_mode" in sec.scopes

    def test_scope_validator_returning_empty_grants_no_scopes(self):
        """A validator that rejects the token returns []; token is present but scopeless."""
        def validator(token: str) -> list[str]:
            return []  # invalid / expired token

        scheme = BearerAuth(scopes=["admin"], scope_validator=validator)
        ctx = {"headers": {"authorization": "Bearer bad_token"}}
        sec = scheme.extract(ctx)

        assert sec.token == "bad_token"   # token extracted
        assert sec.scopes == []            # but no scopes granted

    def test_no_scope_validator_still_grants_declared_scopes_as_fallback(self):
        """Without scope_validator, declared scopes are granted (backward compat).

        This documents the INTENTIONAL behaviour: without a validator ProdMCP
        grants the declared scopes (presence-only check) and emits a UserWarning.
        This test ensures the compat path still works after the Bug 4 fix.
        """
        import warnings
        scheme = BearerAuth(scopes=["read"])   # warning emitted at construction
        ctx = {"headers": {"authorization": "Bearer tok"}}
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            sec = scheme.extract(ctx)
        assert sec.scopes == ["read"]

    def test_scope_validator_warning_emitted_at_construction_not_per_request(self):
        """Bug P3-3 regression: warning fires once at __init__, never inside extract()."""
        import warnings

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            scheme = BearerAuth(scopes=["admin"])   # should emit exactly 1 warning here

        construction_warnings = [w for w in caught if issubclass(w.category, UserWarning)]
        assert len(construction_warnings) == 1, (
            "UserWarning must fire exactly once at construction, got "
            f"{len(construction_warnings)}"
        )

        # Now call extract() multiple times — no new warnings
        ctx = {"headers": {"authorization": "Bearer tok"}}
        with warnings.catch_warnings(record=True) as request_warnings:
            warnings.simplefilter("always")
            for _ in range(5):
                scheme.extract(ctx)

        extra = [w for w in request_warnings if issubclass(w.category, UserWarning)]
        assert len(extra) == 0, (
            f"UserWarning must NOT fire on each request call, but got {len(extra)} "
            "warnings across 5 extract() calls — this is log spam."
        )


# ── BS-2 / BS-3 ───────────────────────────────────────────────────────────────


class TestSecuritySpecContent:
    """BS-2 / BS-3 regression: security spec assertions must check content, not just keys."""

    def _build_app_with_bearer(self):
        from unittest.mock import MagicMock
        from prodmcp.app import ProdMCP

        app = ProdMCP("SpecTest")
        app._mcp = MagicMock()

        @app.tool(
            name="secure_tool",
            security=[{"type": "bearer", "scopes": ["read", "write"]}],
        )
        def secure_tool():
            return "ok"

        return app

    def test_security_spec_content_not_just_presence(self):
        app = self._build_app_with_bearer()
        spec = app.export_openmcp()

        tool_sec = spec["tools"]["secure_tool"]["security"]
        # Must not just exist — must be the correct reference format
        assert tool_sec == [{"bearerAuth": ["read", "write"]}], (
            f"Expected [{{\"bearerAuth\": [\"read\", \"write\"]}}], got {tool_sec}"
        )

    def test_security_scheme_dict_has_correct_type_and_scheme(self):
        app = self._build_app_with_bearer()
        spec = app.export_openmcp()

        bearer_spec = spec["components"]["securitySchemes"].get("bearerAuth")
        assert bearer_spec is not None, "bearerAuth must appear in securitySchemes"
        assert bearer_spec.get("type") == "http", (
            f"Expected type='http', got {bearer_spec.get('type')}"
        )
        assert bearer_spec.get("scheme") == "bearer", (
            f"Expected scheme='bearer', got {bearer_spec.get('scheme')}"
        )

    def test_apikey_scheme_has_correct_fields(self):
        from unittest.mock import MagicMock
        from prodmcp.app import ProdMCP

        app = ProdMCP("ApiKeySpecTest")
        app._mcp = MagicMock()

        @app.tool(
            name="apikey_tool",
            security=[{"type": "apikey", "key_name": "X-Custom-Key", "in": "header"}],
        )
        def apikey_tool():
            return "ok"

        spec = app.export_openmcp()
        scheme_name = "apiKeyAuth_header_X-Custom-Key"
        sec_schemes = spec["components"]["securitySchemes"]

        assert scheme_name in sec_schemes, (
            f"Expected scheme '{scheme_name}' in securitySchemes, "
            f"got keys: {list(sec_schemes.keys())}"
        )
        assert sec_schemes[scheme_name]["type"] == "apiKey"
        assert sec_schemes[scheme_name]["name"] == "X-Custom-Key"
        assert sec_schemes[scheme_name]["in"] == "header"


# ── BS-4 ──────────────────────────────────────────────────────────────────────


class TestAndSemanticsInSecurityRequirements:
    """BS-4 regression: a single requirement dict with multiple keys means AND
    (all schemes must pass).  The Bug E fix in _check_requirement added this
    behaviour but there was no test for it.
    """

    def _mgr_with_both_schemes(self):
        from prodmcp.security.api_key import APIKeyHeader
        mgr = SecurityManager()
        mgr.register_scheme("bearerAuth", BearerAuth())
        mgr.register_scheme("apiKeyAuth", APIKeyHeader(name="X-API-Key"))
        return mgr

    def test_and_semantics_both_present_passes(self):
        """Both bearer AND apikey present → passes."""
        mgr = self._mgr_with_both_schemes()
        ctx = {
            "headers": {
                "authorization": "Bearer tok",
                "x-api-key": "mykey",
            }
        }
        sec = mgr.check(ctx, [{"bearerAuth": [], "apiKeyAuth": []}])
        assert sec is not None

    def test_and_semantics_only_bearer_fails(self):
        """AND requirement: bearer present but apikey missing → must fail."""
        mgr = self._mgr_with_both_schemes()
        ctx = {"headers": {"authorization": "Bearer tok"}}
        with pytest.raises(ProdMCPSecurityError):
            mgr.check(ctx, [{"bearerAuth": [], "apiKeyAuth": []}])

    def test_and_semantics_only_apikey_fails(self):
        """AND requirement: apikey present but bearer missing → must fail."""
        mgr = self._mgr_with_both_schemes()
        ctx = {"headers": {"x-api-key": "mykey"}}
        with pytest.raises(ProdMCPSecurityError):
            mgr.check(ctx, [{"bearerAuth": [], "apiKeyAuth": []}])

    def test_and_vs_or_semantics_are_distinct(self):
        """Two separate dicts in the list is OR (not AND)."""
        mgr = self._mgr_with_both_schemes()
        # Only bearer present — satisfies the first requirement (OR)
        ctx = {"headers": {"authorization": "Bearer tok"}}
        sec = mgr.check(ctx, [{"bearerAuth": []}, {"apiKeyAuth": []}])
        assert sec.token == "tok"


# ── BS-5 ──────────────────────────────────────────────────────────────────────


class TestCustomAuthErrorMessage:
    """BS-5 regression: CustomAuth must surface the real exception type in the error
    message so developers can distinguish auth failures from programmer bugs.
    """

    def test_non_auth_exception_includes_type_name_in_message(self):
        """P3-N4: TypeError from user extractor must not become a vague 'Custom auth failed'."""
        def bad_extractor(ctx):
            # Simulates a bug in user code — TypeError from wrong attribute access
            raise TypeError("object has no attribute 'foo'")

        from prodmcp.security.base import CustomAuth
        scheme = CustomAuth(extractor=bad_extractor)

        with pytest.raises(ProdMCPSecurityError) as exc_info:
            scheme.extract({})

        # The exception type name MUST appear in the error message
        msg = str(exc_info.value)
        assert "TypeError" in msg, (
            f"Expected 'TypeError' in error message to help debug the root cause, "
            f"got: {msg!r}"
        )

    def test_attribute_error_in_extractor_includes_type_name(self):
        def attr_extractor(ctx):
            raise AttributeError("'NoneType' has no attribute 'token'")

        from prodmcp.security.base import CustomAuth
        scheme = CustomAuth(extractor=attr_extractor)

        with pytest.raises(ProdMCPSecurityError, match="AttributeError"):
            scheme.extract({})

    def test_prodmcp_security_error_raised_directly_is_not_rewrapped(self):
        """A ProdMCPSecurityError from the extractor must propagate unchanged."""
        def auth_extractor(ctx):
            raise ProdMCPSecurityError("invalid token", scheme="custom")

        from prodmcp.security.base import CustomAuth
        scheme = CustomAuth(extractor=auth_extractor)

        with pytest.raises(ProdMCPSecurityError, match="invalid token"):
            scheme.extract({})


# ── BS-6 ──────────────────────────────────────────────────────────────────────


class TestEmptyKwargsValidation:
    """BS-6 regression: the Bug F fix changed ``if input_schema and kwargs:`` to
    ``if input_schema is not None:``.  Without this fix, calling a wrapped handler
    with NO arguments skips validation entirely even when required fields are missing.
    """

    class RequiredFields(BaseModel):
        x: int
        y: int

    def test_validation_runs_with_empty_kwargs_sync(self):
        """Calling wrapped() with zero args must still validate required fields."""
        def handler(**kw):
            return kw

        wrapped = create_validated_handler(
            handler,
            input_schema=self._strict_schema(),
        )

        # Without Bug F fix, `if input_schema and {}:` → False → skips → returns {}
        # With fix, validation runs → x is required → ProdMCPValidationError
        with pytest.raises(ProdMCPValidationError) as exc_info:
            wrapped()

        errors = exc_info.value.errors
        missing_fields = {e["loc"][0] for e in errors if e.get("loc")}
        assert "x" in missing_fields or "y" in missing_fields, (
            f"Expected missing field errors for 'x' and/or 'y', got: {errors}"
        )

    def _strict_schema(self):
        """JSON Schema dict with required fields and no defaults."""
        return {
            "type": "object",
            "properties": {"x": {"type": "integer"}, "y": {"type": "integer"}},
            "required": ["x", "y"],
        }

    def test_validation_runs_with_empty_kwargs_missing_required_json_schema(self):
        """Empty kwargs → missing required fields in JSON Schema → ProdMCPValidationError."""
        def handler(**kw):
            return kw

        wrapped = create_validated_handler(handler, input_schema=self._strict_schema())

        # Without Bug F fix, `if input_schema and {}:` → False → skips → returns {}
        # With fix, validation runs → x is required → ProdMCPValidationError
        with pytest.raises(ProdMCPValidationError) as exc_info:
            wrapped()

        errors = exc_info.value.errors
        missing_fields = {e["loc"][0] for e in errors if e.get("loc")}
        assert "x" in missing_fields or "y" in missing_fields, (
            f"Expected missing field errors for 'x' and/or 'y', got: {errors}"
        )

    def test_async_validation_runs_with_empty_kwargs(self):
        """Async path must also validate with empty kwargs."""
        import asyncio as _asyncio

        async def handler(**kw):
            return kw

        wrapped = create_validated_handler(handler, input_schema=self._strict_schema())

        with pytest.raises(ProdMCPValidationError):
            _asyncio.run(wrapped())


# ── BS-7 ──────────────────────────────────────────────────────────────────────


class TestBeforeHookFailurePairing:
    """BS-7 regression: Bug P3-2 fixed the before↔after pairing invariant.

    If before[N] raises, middlewares 0..N-1 that already successfully ran their
    before() MUST still get their after() called.  The original test only exercised
    the HANDLER raising — not a before-hook raising.
    """

    def test_after_called_for_entered_middlewares_when_before_fails(self):
        """Middleware 0 before() OK → Middleware 1 before() FAILS.
        Middleware 0's after() MUST still be called (it 'entered').
        """
        import asyncio as _asyncio
        from prodmcp.middleware import Middleware, MiddlewareContext, MiddlewareManager, build_middleware_chain

        after_calls: list[str] = []

        class SuccessfulMiddleware(Middleware):
            async def before(self, ctx: MiddlewareContext) -> None:
                pass  # succeeds

            async def after(self, ctx: MiddlewareContext) -> None:
                after_calls.append("successful_mw_after")

        class FailingBeforeMiddleware(Middleware):
            async def before(self, ctx: MiddlewareContext) -> None:
                raise RuntimeError("before hook exploded")

            async def after(self, ctx: MiddlewareContext) -> None:
                after_calls.append("failing_mw_after")  # should NOT be called

        mgr = MiddlewareManager()
        mgr.add(SuccessfulMiddleware())
        mgr.add(FailingBeforeMiddleware())

        async def handler():
            return 42

        wrapped = build_middleware_chain(handler, mgr, None, "tool", "test")

        with pytest.raises(RuntimeError, match="before hook exploded"):
            _asyncio.run(wrapped())

        # SuccessfulMiddleware entered (before ran OK) → its after MUST be called
        assert "successful_mw_after" in after_calls, (
            "SuccessfulMiddleware.after() was not called after a later before() failed. "
            "This violates the before↔after pairing invariant (Bug P3-2 regression)."
        )
        # FailingBeforeMiddleware never fully entered → its after must NOT be called
        assert "failing_mw_after" not in after_calls, (
            "FailingBeforeMiddleware.after() should not be called — its before() failed "
            "so it never 'entered'."
        )

    def test_no_after_calls_if_all_before_hooks_fail(self):
        """If the very first before() raises, no after() should be called at all."""
        import asyncio as _asyncio
        from prodmcp.middleware import Middleware, MiddlewareContext, MiddlewareManager, build_middleware_chain

        after_calls: list[str] = []

        class ImmediatelyFailingMiddleware(Middleware):
            async def before(self, ctx: MiddlewareContext) -> None:
                raise RuntimeError("instant failure")

            async def after(self, ctx: MiddlewareContext) -> None:
                after_calls.append("should_not_run")

        mgr = MiddlewareManager()
        mgr.add(ImmediatelyFailingMiddleware())

        async def handler():
            return 1

        wrapped = build_middleware_chain(handler, mgr, None, "tool", "t")

        with pytest.raises(RuntimeError):
            _asyncio.run(wrapped())

        assert after_calls == [], (
            "after() must not be called for middleware whose before() failed."
        )

    def test_handler_failure_still_calls_all_after_hooks(self):
        """Existing behaviour: handler failure must still trigger all after() hooks."""
        import asyncio as _asyncio
        from prodmcp.middleware import Middleware, MiddlewareContext, MiddlewareManager, build_middleware_chain

        after_calls: list[str] = []

        class TrackAfter(Middleware):
            def __init__(self, label: str):
                self.label = label

            async def after(self, ctx: MiddlewareContext) -> None:
                after_calls.append(self.label)

        mgr = MiddlewareManager()
        mgr.add(TrackAfter("mw1"))
        mgr.add(TrackAfter("mw2"))

        def handler():
            raise ValueError("handler crashed")

        wrapped = build_middleware_chain(handler, mgr, None, "tool", "t")

        with pytest.raises(ValueError):
            _asyncio.run(wrapped())

        # Both middlewares entered → both afters must run (in reverse order)
        assert after_calls == ["mw2", "mw1"], (
            f"Expected after calls in reverse order ['mw2', 'mw1'], got {after_calls}"
        )


# ── BS-8 ──────────────────────────────────────────────────────────────────────


class TestJsonSchemaArrayAndScalarValidation:
    """BS-8 regression: P3-N1 added array, scalar, and enum validation to
    _validate_json_schema.  These code paths had zero test coverage.
    """

    # --- array ---

    def test_array_type_accepts_list(self):
        schema = {"type": "array"}
        result = validate_data(["a", "b", "c"], schema, direction="input")
        assert result == ["a", "b", "c"]

    def test_array_type_rejects_dict(self):
        schema = {"type": "array"}
        with pytest.raises(ProdMCPValidationError, match="expected array"):
            validate_data({"not": "a list"}, schema, direction="input")

    def test_array_type_rejects_string(self):
        schema = {"type": "array"}
        with pytest.raises(ProdMCPValidationError, match="expected array"):
            validate_data("hello", schema, direction="input")

    def test_array_items_validated_recursively(self):
        schema = {"type": "array", "items": {"type": "integer"}}
        # Integer items pass
        result = validate_data([1, 2, 3], schema, direction="input")
        assert result == [1, 2, 3]

    def test_array_items_type_mismatch_raises(self):
        schema = {"type": "array", "items": {"type": "integer"}}
        with pytest.raises(ProdMCPValidationError):
            validate_data([1, 2, "not_int"], schema, direction="input")

    def test_array_items_error_includes_index(self):
        schema = {"type": "array", "items": {"type": "integer"}}
        with pytest.raises(ProdMCPValidationError) as exc_info:
            validate_data([1, "bad", 3], schema, direction="input")
        errors = exc_info.value.errors
        # At least one error should reference index 1
        locs = [e.get("loc", []) for e in errors]
        assert any(1 in loc for loc in locs), (
            f"Expected error at index 1, got locs: {locs}"
        )

    # --- string scalar ---

    def test_string_type_valid(self):
        schema = {"type": "string"}
        assert validate_data("hello", schema, direction="input") == "hello"

    def test_string_type_rejects_integer(self):
        schema = {"type": "string"}
        with pytest.raises(ProdMCPValidationError, match="expected string"):
            validate_data(42, schema, direction="input")

    # --- integer scalar ---

    def test_integer_type_valid(self):
        schema = {"type": "integer"}
        assert validate_data(42, schema, direction="input") == 42

    def test_integer_type_rejects_float(self):
        schema = {"type": "integer"}
        with pytest.raises(ProdMCPValidationError, match="expected integer"):
            validate_data(3.14, schema, direction="input")

    def test_integer_type_rejects_bool(self):
        """In JSON, booleans are NOT integers (RFC 7159 §6)."""
        schema = {"type": "integer"}
        with pytest.raises(ProdMCPValidationError):
            validate_data(True, schema, direction="input")

    # --- number scalar ---

    def test_number_type_accepts_int_and_float(self):
        schema = {"type": "number"}
        assert validate_data(3, schema, direction="input") == 3
        assert validate_data(3.14, schema, direction="input") == 3.14

    def test_number_type_rejects_bool(self):
        schema = {"type": "number"}
        with pytest.raises(ProdMCPValidationError):
            validate_data(False, schema, direction="input")

    # --- boolean scalar ---

    def test_boolean_type_valid(self):
        schema = {"type": "boolean"}
        assert validate_data(True, schema, direction="input") is True

    def test_boolean_type_rejects_integer(self):
        schema = {"type": "boolean"}
        with pytest.raises(ProdMCPValidationError, match="expected boolean"):
            validate_data(1, schema, direction="input")

    # --- enum ---

    def test_enum_valid_value_passes(self):
        schema = {"type": "string", "enum": ["a", "b", "c"]}
        assert validate_data("b", schema, direction="input") == "b"

    def test_enum_invalid_value_raises(self):
        schema = {"type": "string", "enum": ["a", "b", "c"]}
        with pytest.raises(ProdMCPValidationError, match="not one of"):
            validate_data("d", schema, direction="input")

    def test_enum_without_type_still_validates(self):
        """enum can appear without an explicit type restriction."""
        schema = {"enum": [1, 2, 3]}
        assert validate_data(2, schema, direction="input") == 2
        with pytest.raises(ProdMCPValidationError):
            validate_data(4, schema, direction="input")

    # --- unknown types pass through ---

    def test_unknown_type_passes_through(self):
        """Unknown schema types must not raise — pass data through unchanged."""
        schema = {"type": "null"}
        result = validate_data(None, schema, direction="input")
        assert result is None

    # --- combinators pass through ---

    def test_allof_passes_through(self):
        """allOf, anyOf, oneOf — not evaluated, data passes through."""
        schema = {"allOf": [{"type": "string"}]}
        # Even with wrong type, passes through (full validator not implemented)
        result = validate_data(42, schema, direction="input")
        assert result == 42


# ── BS-9 ──────────────────────────────────────────────────────────────────────


class TestResolveSchemaIsolation:
    """BS-9 regression: P3-N2 added copy.deepcopy to resolve_schema.
    Without it, mutating the returned dict corrupts Pydantic's internal schema cache
    and subsequent calls return the mutated version.
    """

    class MyModel(BaseModel):
        name: str
        value: int

    def test_mutating_returned_schema_does_not_affect_next_call(self):
        """Mutating the dict returned by resolve_schema must not corrupt the cache."""
        schema1 = resolve_schema(self.MyModel)

        # Mutate the returned dict — simulates what downstream code might do
        schema1["INJECTED_KEY"] = "injected_value"
        schema1.get("properties", {})["FAKE_FIELD"] = {"type": "string"}

        # Second call must return a pristine schema
        schema2 = resolve_schema(self.MyModel)

        assert "INJECTED_KEY" not in schema2, (
            "resolve_schema returned a reference to Pydantic's internal cache; "
            "a mutation in one call bled into the next (P3-N2 regression)."
        )
        assert "FAKE_FIELD" not in schema2.get("properties", {}), (
            "Properties dict was shared between calls — deep copy not working."
        )

    def test_each_call_returns_independent_dict(self):
        """Two successive calls must return different dict objects."""
        schema1 = resolve_schema(self.MyModel)
        schema2 = resolve_schema(self.MyModel)
        assert schema1 is not schema2, (
            "resolve_schema returned the same dict object twice — not deep copying."
        )

    def test_properties_dict_is_independent(self):
        """Mutating the nested 'properties' dict must not bleed through."""
        schema1 = resolve_schema(self.MyModel)
        if "properties" in schema1:
            schema1["properties"]["INJECTED"] = {"type": "boolean"}

        schema2 = resolve_schema(self.MyModel)
        assert "INJECTED" not in schema2.get("properties", {})


# ── BS-12 ─────────────────────────────────────────────────────────────────────


class TestApiKeyHeaderCaseInsensitive:
    """BS-12 regression: N2 fixed APIKeyHeader to be RFC 7230 case-insensitive.

    The original test used the exact same casing as the declared key_name —
    so it passed even if normalization was missing.  These tests use different
    casings to actually exercise the fix.
    """

    @pytest.mark.parametrize("header_casing", [
        "x-api-key",          # all lowercase
        "X-API-KEY",          # all uppercase
        "X-Api-Key",          # title case
        "x-API-key",          # mixed case
        "X-api-KEY",          # another mix
    ])
    def test_key_found_regardless_of_header_casing(self, header_casing):
        """RFC 7230: header names are case-insensitive."""
        scheme = APIKeyHeader(name="X-API-Key")
        context = {"headers": {header_casing: "my-secret-value"}}

        sec = scheme.extract(context)

        assert sec.token == "my-secret-value", (
            f"APIKeyHeader(name='X-API-Key') failed to find header '{header_casing}'. "
            "RFC 7230 requires case-insensitive header matching (N2 regression)."
        )

    def test_declared_name_casing_is_also_found_exactly(self):
        """The exact declared key_name casing must also work (sanity check)."""
        scheme = APIKeyHeader(name="X-API-Key")
        context = {"headers": {"X-API-Key": "value"}}
        assert scheme.extract(context).token == "value"

    def test_wrong_header_name_raises_regardless_of_casing(self):
        """A completely different header must still be rejected."""
        scheme = APIKeyHeader(name="X-API-Key")
        context = {"headers": {"Authorization": "Bearer tok"}}
        with pytest.raises(ProdMCPSecurityError):
            scheme.extract(context)

    def test_api_key_auth_shim_also_case_insensitive(self):
        """The backwards-compat ApiKeyAuth shim must inherit case-insensitivity."""
        from prodmcp.security import ApiKeyAuth
        scheme = ApiKeyAuth(key_name="X-Custom-Header", location="header")
        context = {"headers": {"x-custom-header": "secret"}}
        sec = scheme.extract(context)
        assert sec.token == "secret"


# ── BS-14 ─────────────────────────────────────────────────────────────────────


class TestMultilineDocstringExactSummary:
    """BS-14 regression: N5 fix uses only the first non-empty docstring line as the
    route summary.  The original test used ``in`` which passes even if the full
    multiline docstring is used.
    """

    def test_route_summary_uses_only_first_docstring_line(self):
        """When no explicit summary is given, the route summary must be only line 1."""
        try:
            from fastapi.testclient import TestClient
        except ImportError:
            pytest.skip("FastAPI not installed")

        from unittest.mock import MagicMock
        from prodmcp.app import ProdMCP
        from prodmcp.router import create_unified_app

        app = ProdMCP("SummaryTest")
        app._mcp = MagicMock()

        @app.get("/multi-doc")
        def handler_with_multiline_doc():
            """First summary line.

            Extended description that should NOT appear in the route summary.
            This paragraph is deliberately verbose.
            """
            return {}

        fastapi_app = create_unified_app(app)
        route = next(
            r for r in fastapi_app.routes if getattr(r, "path", None) == "/multi-doc"
        )

        # FastAPI sets route.summary to either the explicit summary or derives it
        # from the endpoint function. ProdMCP's N5 fix truncates the docstring to
        # the first non-empty line before passing it as 'summary' to add_api_route.
        if route.summary:
            assert "Extended description" not in route.summary, (
                "Route summary must not contain lines beyond the first. "
                f"Got: {route.summary!r}"
            )

    def test_tool_description_stores_full_docstring_not_just_first_line(self):
        """Tool descriptions (for MCP) should store the full docstring.
        N5 only applies to the REST route summary — not the tool meta description.
        """
        from prodmcp.app import ProdMCP

        app = ProdMCP("DocTest")

        @app.tool()
        def documented():
            """First line.

            Second paragraph with more detail.
            """
            return {}

        meta = app.get_tool_meta("documented")
        # Full docstring is stored for tool description (used by MCP clients)
        assert "First line." in meta["description"]
        # Verify it's the actual stripped docstring content
        assert meta["description"].strip().startswith("First line.")


# ── BS-16 ─────────────────────────────────────────────────────────────────────


class TestCommonSecurityShorthandFormat:
    """BS-16 regression: test_common_provides_security_to_tool in test_common_decorator.py
    used the dict-key format {\"bearer\": [\"read\"]} (looks for a registered scheme named
    'bearer'), not the ProdMCP shorthand format {\"type\": \"bearer\"}.  This means the
    test was silently misconfigured.
    """

    def test_common_security_with_correct_shorthand_format(self):
        """@app.common(security=[{\"type\": \"bearer\", \"scopes\": [...]}]) must work."""
        from prodmcp.app import ProdMCP

        app = ProdMCP("ShorthandTest")

        @app.common(security=[{"type": "bearer", "scopes": ["read"]}])
        @app.tool(name="secured")
        def secured():
            return "ok"

        meta = app.get_tool_meta("secured")
        # Security config must contain the bearer requirement
        security = meta["security"]
        assert len(security) >= 1, "Security config must not be empty"
        # The stored config must be the normalized version
        assert any(
            "bearerAuth" in req or req.get("type") == "bearer"
            for req in security
        ), f"Expected bearer requirement, got: {security}"

    def test_common_security_shorthand_registers_scheme_at_registration_time(self):
        """P3-5 regression: shorthand schemes must be auto-registered in _schemes
        after finalization (when _build_handler is called by _finalize_pending).
        """
        from unittest.mock import MagicMock
        from prodmcp.app import ProdMCP

        app = ProdMCP("AutoRegTest")
        app._mcp = MagicMock()  # prevent real FastMCP registration

        @app.tool(
            name="auto_registered",
            security=[{"type": "bearer", "scopes": []}],
        )
        def auto_registered():
            return "ok"

        # Auto-registration happens inside _build_handler, called by _finalize_pending
        app._finalize_pending()

        # After finalization, bearerAuth must be in _security_manager._schemes
        assert "bearerAuth" in app._security_manager._schemes, (
            "Shorthand bearer scheme was not auto-registered into _security_manager._schemes "
            "after finalization. Spec generation will not include the scheme definition."
        )

    def test_spec_includes_shorthand_scheme_definition(self):
        """Spec must include the 'bearerAuth' scheme definition even when only shorthand is used."""
        from unittest.mock import MagicMock
        from prodmcp.app import ProdMCP

        app = ProdMCP("ShorthandSpecTest")
        app._mcp = MagicMock()

        @app.tool(
            name="tool1",
            security=[{"type": "bearer", "scopes": ["admin"]}],
        )
        def tool1():
            return "ok"

        spec = app.export_openmcp()
        sec_schemes = spec["components"]["securitySchemes"]

        assert "bearerAuth" in sec_schemes, (
            "'bearerAuth' scheme definition is missing from the OpenMCP spec. "
            "Shorthand security must auto-register the scheme (P3-5 fix)."
        )
        assert sec_schemes["bearerAuth"]["type"] == "http"
        assert sec_schemes["bearerAuth"]["scheme"] == "bearer"


# ── Bonus: generate_spec must not mutate _schemes (P3-5) ─────────────────────


class TestSpecGenerationReadOnly:
    """Bug P3-5 regression: generate_security_spec() must be a pure read-only
    operation — calling it must not register new schemes into _schemes.
    """

    def test_generate_security_spec_does_not_mutate_schemes(self):
        """Calling generate_security_spec() on a manager with NO registered schemes
        must not register 'bearerAuth' as a side effect.
        """
        mgr = SecurityManager()
        assert len(mgr._schemes) == 0  # start clean

        mgr.generate_security_spec([{"type": "bearer", "scopes": ["user"]}])

        assert len(mgr._schemes) == 0, (
            "generate_security_spec() must NOT register schemes into _schemes "
            "(Bug P3-5 fix regression). It is a read-only spec-building method."
        )

    def test_generate_security_spec_idempotent(self):
        """Calling generate_security_spec() multiple times must return the same result."""
        mgr = SecurityManager()
        config = [{"type": "bearer", "scopes": ["r", "w"]}]

        result1 = mgr.generate_security_spec(config)
        result2 = mgr.generate_security_spec(config)
        result3 = mgr.generate_security_spec(config)

        assert result1 == result2 == result3
