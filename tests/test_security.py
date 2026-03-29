"""Tests for the security layer."""

import pytest

from prodmcp.exceptions import ProdMCPSecurityError
from prodmcp.security import (
    ApiKeyAuth,
    BearerAuth,
    CustomAuth,
    SecurityContext,
    SecurityManager,
)


# ── BearerAuth ─────────────────────────────────────────────────────────


class TestBearerAuth:
    def test_extract_valid(self):
        scheme = BearerAuth(scopes=["user", "admin"])
        context = {"headers": {"authorization": "Bearer my-token-123"}}
        sec = scheme.extract(context)
        assert sec.token == "my-token-123"
        assert sec.scopes == ["user", "admin"]

    def test_extract_missing_header(self):
        scheme = BearerAuth()
        context = {"headers": {}}
        with pytest.raises(ProdMCPSecurityError):
            scheme.extract(context)

    def test_extract_wrong_scheme(self):
        scheme = BearerAuth()
        context = {"headers": {"authorization": "Basic abc123"}}
        with pytest.raises(ProdMCPSecurityError):
            scheme.extract(context)

    def test_to_spec(self):
        scheme = BearerAuth()
        spec = scheme.to_spec()
        assert spec["type"] == "http"
        assert spec["scheme"] == "bearer"


# ── ApiKeyAuth ─────────────────────────────────────────────────────────


class TestApiKeyAuth:
    def test_extract_header(self):
        scheme = ApiKeyAuth(key_name="X-API-Key", location="header")
        context = {"headers": {"X-API-Key": "secret-key"}}
        sec = scheme.extract(context)
        assert sec.token == "secret-key"

    def test_extract_query(self):
        scheme = ApiKeyAuth(key_name="api_key", location="query")
        context = {"query_params": {"api_key": "secret-key"}}
        sec = scheme.extract(context)
        assert sec.token == "secret-key"

    def test_missing_key(self):
        scheme = ApiKeyAuth()
        context = {"headers": {}}
        with pytest.raises(ProdMCPSecurityError):
            scheme.extract(context)

    def test_to_spec(self):
        scheme = ApiKeyAuth(key_name="X-API-Key", location="header")
        spec = scheme.to_spec()
        assert spec["type"] == "apiKey"
        assert spec["name"] == "X-API-Key"
        assert spec["in"] == "header"


# ── CustomAuth ─────────────────────────────────────────────────────────


class TestCustomAuth:
    def test_custom_extractor(self):
        def my_extractor(ctx):
            return SecurityContext(user={"id": "admin"}, token="custom")

        scheme = CustomAuth(extractor=my_extractor)
        sec = scheme.extract({})
        assert sec.user == {"id": "admin"}
        assert sec.token == "custom"

    def test_custom_failure(self):
        def failing_extractor(ctx):
            raise ValueError("nope")

        scheme = CustomAuth(extractor=failing_extractor)
        with pytest.raises(ProdMCPSecurityError):
            scheme.extract({})


# ── SecurityManager ────────────────────────────────────────────────────


class TestSecurityManager:
    def test_no_security_config(self):
        mgr = SecurityManager()
        sec = mgr.check({}, [])
        assert isinstance(sec, SecurityContext)

    def test_shorthand_bearer(self):
        mgr = SecurityManager()
        context = {"headers": {"authorization": "Bearer tok123"}}
        sec = mgr.check(context, [{"type": "bearer", "scopes": []}])
        assert sec.token == "tok123"

    def test_shorthand_bearer_fails(self):
        mgr = SecurityManager()
        context = {"headers": {}}
        with pytest.raises(ProdMCPSecurityError):
            mgr.check(context, [{"type": "bearer"}])

    def test_named_scheme(self):
        mgr = SecurityManager()
        mgr.register_scheme("bearerAuth", BearerAuth(scopes=["user"]))
        context = {"headers": {"authorization": "Bearer tok"}}
        sec = mgr.check(context, [{"bearerAuth": []}])
        assert sec.token == "tok"

    def test_or_semantics(self):
        """Security requirements are ORed — one passing is enough."""
        mgr = SecurityManager()
        mgr.register_scheme("apiKeyAuth", ApiKeyAuth())
        context = {"headers": {"X-API-Key": "abc"}}
        # First requirement (bearer) will fail, second (apiKey) passes
        sec = mgr.check(
            context,
            [
                {"type": "bearer"},
                {"apiKeyAuth": []},
            ],
        )
        assert sec.token == "abc"

    def test_generate_schemes_spec(self):
        mgr = SecurityManager()
        mgr.register_scheme("bearerAuth", BearerAuth())
        mgr.register_scheme("apiKeyAuth", ApiKeyAuth())
        spec = mgr.generate_schemes_spec()
        assert "bearerAuth" in spec
        assert "apiKeyAuth" in spec
        assert spec["bearerAuth"]["type"] == "http"

    def test_generate_security_spec_shorthand(self):
        mgr = SecurityManager()
        result = mgr.generate_security_spec(
            [{"type": "bearer", "scopes": ["user"]}]
        )
        assert result == [{"bearerAuth": ["user"]}]
        assert "bearerAuth" in mgr._schemes

class TestNewSecuritySchemes:
    def test_http_basic_auth(self):
        from prodmcp.security import HTTPBasicAuth
        scheme = HTTPBasicAuth()
        
        ctx = scheme.extract({"headers": {"authorization": "Basic QWxhZGRpbjpvcGVuIHNlc2FtZQ=="}})
        assert ctx.token == "open sesame"
        assert ctx.metadata["username"] == "Aladdin"
        assert scheme.to_spec() == {"type": "http", "scheme": "basic"}

    def test_api_key_cookie(self):
        from prodmcp.security import APIKeyCookie
        scheme = APIKeyCookie(name="session_id")
        
        ctx = scheme.extract({"cookies": {"session_id": "foobar123"}})
        assert ctx.token == "foobar123"
        assert scheme.to_spec() == {"type": "apiKey", "name": "session_id", "in": "cookie"}

    def test_oauth2_password_bearer(self):
        from prodmcp.security import OAuth2PasswordBearer
        scheme = OAuth2PasswordBearer(tokenUrl="https://example.com/token", scopes={"read": "Read access"})
        
        ctx = scheme.extract({"headers": {"authorization": "Bearer super_token"}})
        assert ctx.token == "super_token"
        assert ctx.scopes == ["read"]
        assert scheme.to_spec() == {
            "type": "oauth2",
            "flows": {"password": {"tokenUrl": "https://example.com/token", "scopes": {"read": "Read access"}}}
        }

    def test_open_id_connect(self):
        from prodmcp.security import OpenIdConnect
        scheme = OpenIdConnect(openIdConnectUrl="https://example.com/.well-known/openid-configuration")
        
        ctx = scheme.extract({"headers": {"authorization": "Bearer oidc_token"}})
        assert ctx.token == "oidc_token"
        assert scheme.to_spec() == {
            "type": "openIdConnect",
            "openIdConnectUrl": "https://example.com/.well-known/openid-configuration"
        }
