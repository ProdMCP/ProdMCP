"""Tests for the ProdMCP constructor and initialization."""


from prodmcp.app import ProdMCP


class TestConstructorFastMCPStyle:
    """ProdMCP must work as a drop-in replacement for FastMCP's constructor."""

    def test_positional_name(self):
        app = ProdMCP("MyServer")
        assert app.name == "MyServer"

    def test_name_with_version(self):
        app = ProdMCP("MyServer", version="2.0.0")
        assert app.name == "MyServer"
        assert app.version == "2.0.0"

    def test_name_with_description(self):
        app = ProdMCP("MyServer", description="A test server")
        assert app.description == "A test server"

    def test_defaults(self):
        app = ProdMCP()
        assert app.name == "ProdMCP Server"
        assert app.version == "1.0.0"
        assert app.description == ""
        assert app.strict_output is True
        assert app.mcp_path == "/mcp"


class TestConstructorFastAPIStyle:
    """ProdMCP must accept FastAPI-style keyword 'title'."""

    def test_title_keyword(self):
        app = ProdMCP(title="UserService")
        assert app.name == "UserService"

    def test_title_with_version_and_description(self):
        app = ProdMCP(title="UserService", version="3.0.0", description="Users API")
        assert app.name == "UserService"
        assert app.version == "3.0.0"
        assert app.description == "Users API"

    def test_title_overrides_default_name(self):
        """When title is provided, it should override the default name."""
        app = ProdMCP(title="TitleWins")
        assert app.name == "TitleWins"

    def test_positional_name_over_title_none(self):
        """When positional name is given but title is None, name wins."""
        app = ProdMCP("PositionalName", title=None)
        assert app.name == "PositionalName"


class TestConstructorMCPPath:
    """The mcp_path parameter controls where MCP SSE is mounted."""

    def test_default_mcp_path(self):
        app = ProdMCP("T")
        assert app.mcp_path == "/mcp"

    def test_custom_mcp_path(self):
        app = ProdMCP("T", mcp_path="/custom-mcp")
        assert app.mcp_path == "/custom-mcp"

    def test_root_mcp_path(self):
        app = ProdMCP("T", mcp_path="/")
        assert app.mcp_path == "/"

    def test_nested_mcp_path(self):
        app = ProdMCP("T", mcp_path="/api/v2/mcp")
        assert app.mcp_path == "/api/v2/mcp"


class TestConstructorStrictOutput:
    def test_strict_output_default_true(self):
        app = ProdMCP("T")
        assert app.strict_output is True

    def test_strict_output_false(self):
        app = ProdMCP("T", strict_output=False)
        assert app.strict_output is False


class TestRegistryInitialization:
    def test_all_registries_exist(self):
        app = ProdMCP("T")
        assert "tools" in app._registry
        assert "prompts" in app._registry
        assert "resources" in app._registry
        assert "api" in app._registry

    def test_registries_empty_on_init(self):
        app = ProdMCP("T")
        assert app._registry["tools"] == {}
        assert app._registry["prompts"] == {}
        assert app._registry["resources"] == {}
        assert app._registry["api"] == {}
