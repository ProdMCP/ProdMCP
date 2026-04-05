"""Tests for the run() method behavior."""

from unittest.mock import patch, MagicMock, AsyncMock
import pytest

from prodmcp.app import ProdMCP


class TestRunTransportSelection:
    """run() should pick the correct transport mode."""

    def test_run_stdio_delegates_to_fastmcp(self):
        app = ProdMCP("T")
        app._mcp = MagicMock()

        app.run(transport="stdio")

        app._mcp.run.assert_called_once_with(transport="stdio")

    def test_run_sse_calls_run_http_async(self):
        """SSE transport must use run_http_async() so middleware can be injected."""
        app = ProdMCP("T")
        app._mcp = MagicMock()

        with patch("anyio.run") as mock_anyio:
            app.run(transport="sse", host="127.0.0.1", port=9000)

        # anyio.run should have been called (wraps run_http_async)
        mock_anyio.assert_called_once()
        # The old self.mcp.run() must NOT be called for sse transport
        app._mcp.run.assert_not_called()

    def test_run_http_transport_uses_run_http_async(self):
        """'http' transport must also use the middleware-aware run_http_async()."""
        app = ProdMCP("T")
        app._mcp = MagicMock()

        with patch("anyio.run") as mock_anyio:
            app.run(transport="http", host="0.0.0.0", port=8000)

        mock_anyio.assert_called_once()
        app._mcp.run.assert_not_called()

    def test_run_streamable_http_transport_uses_run_http_async(self):
        """'streamable-http' transport must also use the middleware-aware path."""
        app = ProdMCP("T")
        app._mcp = MagicMock()

        with patch("anyio.run") as mock_anyio:
            app.run(transport="streamable-http", host="0.0.0.0", port=8000)

        mock_anyio.assert_called_once()
        app._mcp.run.assert_not_called()

    @patch("prodmcp.app.ProdMCP._finalize_pending")
    def test_run_unified_calls_finalize(self, mock_finalize):
        """Unified mode should finalize pending registrations."""
        app = ProdMCP("T")
        app._mcp = MagicMock()

        with patch("prodmcp.router.create_unified_app") as mock_router:
            mock_router.return_value = MagicMock()
            with patch("uvicorn.run"):
                app.run(transport="unified")

        mock_finalize.assert_called()

    @patch("prodmcp.app.ProdMCP._finalize_pending")
    def test_run_default_is_unified(self, mock_finalize):
        """Default transport should be 'unified'."""
        app = ProdMCP("T")
        app._mcp = MagicMock()

        with patch("prodmcp.router.create_unified_app") as mock_router:
            mock_router.return_value = MagicMock()
            with patch("uvicorn.run"):
                app.run()  # No transport specified

        # Should have gone through unified path (called create_unified_app)
        mock_router.assert_called_once()


class TestRunParameters:
    def test_default_host_and_port(self):
        """Default host should be 0.0.0.0 and port 8000."""
        app = ProdMCP("T")
        app._mcp = MagicMock()

        with patch("prodmcp.router.create_unified_app") as mock_router:
            mock_router.return_value = MagicMock()
            with patch("uvicorn.run") as mock_uvicorn:
                app.run()

        mock_uvicorn.assert_called_once()
        call_kwargs = mock_uvicorn.call_args
        assert call_kwargs.kwargs["host"] == "0.0.0.0"
        assert call_kwargs.kwargs["port"] == 8000

    def test_custom_host_and_port(self):
        app = ProdMCP("T")
        app._mcp = MagicMock()

        with patch("prodmcp.router.create_unified_app") as mock_router:
            mock_router.return_value = MagicMock()
            with patch("uvicorn.run") as mock_uvicorn:
                app.run(host="127.0.0.1", port=3000)

        call_kwargs = mock_uvicorn.call_args
        assert call_kwargs.kwargs["host"] == "127.0.0.1"
        assert call_kwargs.kwargs["port"] == 3000


class TestSSETransportMiddlewareForwarding:
    """Regression: ASGI middlewares must be forwarded to FastMCP's HTTP server
    when using transport='sse', 'http', or 'streamable-http'.

    Before the fix, self.mcp.run() was called directly, bypassing FastMCP's
    own middleware parameter.  Now we call run_http_async(middleware=...).
    """

    def _capture_partial_call(self, mock_anyio):
        """Extract the partial() that was passed to anyio.run()."""
        from functools import partial
        call_args = mock_anyio.call_args
        fn = call_args[0][0]  # first positional arg to anyio.run()
        assert isinstance(fn, partial)
        return fn

    def test_cors_middleware_forwarded_to_fastmcp_sse(self):
        """CORSMiddleware registered on ProdMCP must reach FastMCP's SSE server."""
        from fastapi.middleware.cors import CORSMiddleware
        from starlette.middleware import Middleware as StarletteMiddleware

        app = ProdMCP("T")
        app._mcp = MagicMock()
        app.add_asgi_middleware(CORSMiddleware, allow_origins=["*"])

        with patch("anyio.run") as mock_anyio:
            app.run(transport="sse", host="0.0.0.0", port=8000)

        fn = self._capture_partial_call(mock_anyio)

        # P2-8 fix: verify ALL required keyword args are present, not just two.
        # Spot-checking only transport/host/port would miss a silently dropped
        # 'middleware' parameter — the entire point of the SSE fix.
        assert fn.func is app._mcp.run_http_async
        required_keys = {"transport", "host", "port", "middleware"}
        assert required_keys <= set(fn.keywords.keys()), (
            f"run_http_async partial is missing required keyword args: "
            f"{required_keys - set(fn.keywords.keys())}"
        )
        assert fn.keywords["transport"] == "sse"
        assert fn.keywords["host"] == "0.0.0.0"
        assert fn.keywords["port"] == 8000

        middlewares = fn.keywords["middleware"]
        assert middlewares is not None
        assert len(middlewares) == 1
        assert isinstance(middlewares[0], StarletteMiddleware)
        assert middlewares[0].cls is CORSMiddleware
        assert middlewares[0].kwargs == {"allow_origins": ["*"]}

    def test_no_middleware_passes_none_to_fastmcp(self):
        """When no ASGI middleware is registered, middleware=None is passed."""
        app = ProdMCP("T")
        app._mcp = MagicMock()

        with patch("anyio.run") as mock_anyio:
            app.run(transport="sse")

        fn = self._capture_partial_call(mock_anyio)
        # None is passed when there are no middlewares (not an empty list)
        assert fn.keywords["middleware"] is None

    def test_multiple_middlewares_forwarded_in_order(self):
        """Multiple middlewares must all be forwarded, in registration order."""
        from fastapi.middleware.cors import CORSMiddleware
        from starlette.middleware.gzip import GZipMiddleware

        app = ProdMCP("T")
        app._mcp = MagicMock()
        app.add_asgi_middleware(CORSMiddleware, allow_origins=["*"])
        app.add_asgi_middleware(GZipMiddleware, minimum_size=100)

        with patch("anyio.run") as mock_anyio:
            app.run(transport="http")

        fn = self._capture_partial_call(mock_anyio)
        middlewares = fn.keywords["middleware"]
        assert len(middlewares) == 2
        assert middlewares[0].cls is CORSMiddleware
        assert middlewares[1].cls is GZipMiddleware
