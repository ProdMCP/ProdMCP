"""Tests for the package-level imports and exports.

Ensures that the public API surface is correct for:
- FastMCP migration (from prodmcp import ProdMCP as FastMCP)
- FastAPI migration (from prodmcp import ProdMCP as FastAPI, Depends, HTTPException)
- Native usage (from prodmcp import ProdMCP, BearerAuth, ...)
"""



class TestPublicImports:
    """Verify all public symbols are importable."""

    def test_prodmcp_class(self):
        from prodmcp import ProdMCP
        assert ProdMCP is not None

    def test_depends(self):
        from prodmcp import Depends
        assert Depends is not None

    def test_http_exception(self):
        from prodmcp import HTTPException
        assert HTTPException is not None

    def test_bearer_auth(self):
        from prodmcp import BearerAuth
        assert BearerAuth is not None

    def test_api_key_auth(self):
        from prodmcp import ApiKeyAuth
        assert ApiKeyAuth is not None

    def test_custom_auth(self):
        from prodmcp import CustomAuth
        assert CustomAuth is not None

    def test_security_context(self):
        from prodmcp import SecurityContext
        assert SecurityContext is not None

    def test_security_manager(self):
        from prodmcp import SecurityManager
        assert SecurityManager is not None

    def test_security_scheme(self):
        from prodmcp import SecurityScheme
        assert SecurityScheme is not None

    def test_middleware(self):
        from prodmcp import Middleware
        assert Middleware is not None

    def test_middleware_context(self):
        from prodmcp import MiddlewareContext
        assert MiddlewareContext is not None

    def test_logging_middleware(self):
        from prodmcp import LoggingMiddleware
        assert LoggingMiddleware is not None

    def test_resolve_schema(self):
        from prodmcp import resolve_schema
        assert callable(resolve_schema)

    def test_validate_data(self):
        from prodmcp import validate_data
        assert callable(validate_data)

    def test_generate_spec(self):
        from prodmcp import generate_spec
        assert callable(generate_spec)

    def test_spec_to_json(self):
        from prodmcp import spec_to_json
        assert callable(spec_to_json)

    def test_errors(self):
        from prodmcp import ProdMCPError, ProdMCPValidationError, ProdMCPSecurityError, ProdMCPMiddlewareError
        assert ProdMCPError is not None
        assert ProdMCPValidationError is not None
        assert ProdMCPSecurityError is not None
        assert ProdMCPMiddlewareError is not None


class TestVersion:
    def test_version_is_030(self):
        from prodmcp import __version__
        assert __version__ == "0.3.0"

    def test_version_is_string(self):
        from prodmcp import __version__
        assert isinstance(__version__, str)


class TestAllExports:
    def test_all_list_complete(self):
        import prodmcp
        for name in prodmcp.__all__:
            assert hasattr(prodmcp, name), f"Missing export: {name}"


class TestFastAPIAlias:
    """FastAPI migration pattern: from prodmcp import ProdMCP as FastAPI."""

    def test_alias_works(self):
        from prodmcp import ProdMCP as FastAPI
        app = FastAPI(title="MyAPI", version="1.0.0")
        assert app.name == "MyAPI"

    def test_full_import_line(self):
        from prodmcp import ProdMCP as FastAPI, Depends, HTTPException
        app = FastAPI(title="Test")
        assert app is not None
        assert Depends is not None
        assert HTTPException is not None


class TestFastMCPAlias:
    """FastMCP migration pattern: from prodmcp import ProdMCP as FastMCP."""

    def test_alias_works(self):
        from prodmcp import ProdMCP as FastMCP
        mcp = FastMCP("MyServer")
        assert mcp.name == "MyServer"
