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
    def test_version_is_semver_string(self):
        """Version should be a non-empty semver string (dynamic from package metadata)."""
        from prodmcp import __version__
        assert isinstance(__version__, str)
        assert len(__version__) > 0
        # Basic semver format: at least MAJOR.MINOR.PATCH
        parts = __version__.split(".")
        assert len(parts) >= 3, f"Expected semver format, got {__version__!r}"

    def test_version_is_string(self):
        from prodmcp import __version__
        assert isinstance(__version__, str)


class TestAllExports:
    def test_all_list_complete(self):
        import prodmcp
        for name in prodmcp.__all__:
            assert hasattr(prodmcp, name), f"Missing export: {name}"


class TestASGIMiddlewareExports:
    """Bug 7: ASGI middlewares must be importable directly from prodmcp."""

    def test_cors_middleware_importable(self):
        from prodmcp import CORSMiddleware
        # When [rest] is installed CORSMiddleware is the real Starlette class
        assert CORSMiddleware is not None
        assert callable(CORSMiddleware)

    def test_gzip_middleware_importable(self):
        from prodmcp import GZipMiddleware
        assert GZipMiddleware is not None
        assert callable(GZipMiddleware)

    def test_trusted_host_middleware_importable(self):
        from prodmcp import TrustedHostMiddleware
        assert TrustedHostMiddleware is not None
        assert callable(TrustedHostMiddleware)

    def test_cors_middleware_is_starlette_class(self):
        from prodmcp import CORSMiddleware
        try:
            from starlette.middleware.cors import CORSMiddleware as StarletteCorsMW
            assert CORSMiddleware is StarletteCorsMW
        except ImportError:
            pass  # [rest] not installed — None sentinel is fine

    def test_cors_usage_pattern(self):
        """Verify the fully ProdMCP-only CORS setup pattern works end-to-end."""
        from prodmcp import ProdMCP, CORSMiddleware
        app = ProdMCP(title="CORSTest")
        # Should not raise — CORSMiddleware is valid when [rest] installed
        if CORSMiddleware is not None:
            app.add_asgi_middleware(
                CORSMiddleware,
                allow_origins=["https://myapp.com"],
                allow_methods=["GET", "POST"],
                allow_headers=["*"],
            )
            assert len(app._middleware_manager.asgi_middlewares) == 1


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
