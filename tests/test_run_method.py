"""Tests for the run() method behavior."""

import pytest
from unittest.mock import patch, MagicMock

from prodmcp.app import ProdMCP


class TestRunTransportSelection:
    """run() should pick the correct transport mode."""

    def test_run_stdio_delegates_to_fastmcp(self):
        app = ProdMCP("T")
        app._mcp = MagicMock()

        app.run(transport="stdio")

        app._mcp.run.assert_called_once_with(transport="stdio")

    def test_run_sse_delegates_to_fastmcp(self):
        app = ProdMCP("T")
        app._mcp = MagicMock()

        app.run(transport="sse", host="127.0.0.1", port=9000)

        app._mcp.run.assert_called_once_with(
            transport="sse", host="127.0.0.1", port=9000
        )

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
