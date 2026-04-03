"""Tests for @app.common() decorator and its merging behavior."""

from pydantic import BaseModel

from prodmcp.app import ProdMCP
from prodmcp.middleware import LoggingMiddleware


class InputA(BaseModel):
    name: str

class OutputA(BaseModel):
    result: str

class InputB(BaseModel):
    query: str

class OutputB(BaseModel):
    items: list[str]


class TestCommonWithTool:
    """@app.common() should feed shared config into @app.tool()."""

    def test_common_provides_schemas_to_tool(self):
        app = ProdMCP("T")

        @app.common(input_schema=InputA, output_schema=OutputA)
        @app.tool(name="my_tool")
        def my_tool(name: str) -> dict:
            return {"result": name}

        meta = app.get_tool_meta("my_tool")
        assert meta["input_schema"] is InputA
        assert meta["output_schema"] is OutputA

    def test_common_provides_security_to_tool(self):
        app = ProdMCP("T")

        @app.common(security=[{"bearer": ["read"]}])
        @app.tool(name="secured")
        def secured() -> str:
            return "ok"

        meta = app.get_tool_meta("secured")
        # Security config should be present (may include auto-generated scheme names)
        assert len(meta["security"]) >= 1

    def test_common_provides_middleware_to_tool(self):
        app = ProdMCP("T")
        app.add_middleware(LoggingMiddleware, name="logging")

        @app.common(middleware=["logging"])
        @app.tool(name="logged")
        def logged() -> str:
            return "ok"

        meta = app.get_tool_meta("logged")
        assert "logging" in meta["middleware"]

    def test_common_provides_tags_to_tool(self):
        app = ProdMCP("T")

        @app.common(tags={"admin", "internal"})
        @app.tool(name="tagged")
        def tagged() -> str:
            return "ok"

        meta = app.get_tool_meta("tagged")
        assert meta["tags"] == {"admin", "internal"}

    def test_common_provides_strict_to_tool(self):
        app = ProdMCP("T", strict_output=True)

        @app.common(strict=False)
        @app.tool(name="relaxed")
        def relaxed() -> str:
            return "ok"

        meta = app.get_tool_meta("relaxed")
        assert meta["strict"] is False

    def test_tool_inline_overrides_common(self):
        """When tool provides explicit values, they should override common."""
        app = ProdMCP("T")

        @app.common(input_schema=InputA, output_schema=OutputA)
        @app.tool(name="explicit", input_schema=InputB, output_schema=OutputB)
        def explicit(query: str) -> dict:
            return {"items": []}

        meta = app.get_tool_meta("explicit")
        assert meta["input_schema"] is InputB
        assert meta["output_schema"] is OutputB


class TestCommonWithPrompt:
    def test_common_provides_schemas_to_prompt(self):
        app = ProdMCP("T")

        @app.common(input_schema=InputA, output_schema=OutputA)
        @app.prompt(name="my_prompt")
        def my_prompt(name: str) -> str:
            return f"Hello {name}"

        meta = app.get_prompt_meta("my_prompt")
        assert meta["input_schema"] is InputA
        assert meta["output_schema"] is OutputA


class TestCommonWithResource:
    def test_common_provides_output_to_resource(self):
        app = ProdMCP("T")

        @app.common(output_schema=OutputA)
        @app.resource(uri="data://test", name="test_res")
        def test_res() -> dict:
            return {"result": "ok"}

        meta = app.get_resource_meta("test_res")
        assert meta["output_schema"] is OutputA


class TestCommonWithHttpMethods:
    """@app.common() should feed config into @app.get(), @app.post(), etc."""

    def test_common_with_get(self):
        app = ProdMCP("T")

        @app.common(output_schema=OutputA, security=[{"bearer": []}])
        @app.get("/test", tags=["test"])
        def test_handler() -> dict:
            return {"result": "ok"}

        meta = app._registry["api"]["/test:GET"]
        assert meta["handler"] is test_handler
        # Common config is resolved lazily at build time via _resolve_common flag
        assert meta.get("_resolve_common") is True

    def test_common_response_model_alias(self):
        """@app.common(response_model=...) should work as output_schema alias."""
        app = ProdMCP("T")

        @app.common(response_model=OutputA)
        @app.tool(name="aliased")
        def aliased() -> dict:
            return {"result": "ok"}

        meta = app.get_tool_meta("aliased")
        assert meta["output_schema"] is OutputA


class TestCommonWithStacking:
    """Using @app.common() + @app.tool() + @app.get() on the same function."""

    def test_triple_stack(self):
        app = ProdMCP("T")

        @app.common(input_schema=InputA, output_schema=OutputA)
        @app.tool(name="dual", description="Both API and MCP")
        @app.get("/test/{name}", tags=["test"])
        def handler(name: str) -> dict:
            return {"result": name}

        # Tool should be registered
        assert "dual" in app.list_tools()
        meta = app.get_tool_meta("dual")
        assert meta["input_schema"] is InputA
        assert meta["output_schema"] is OutputA
        assert meta["description"] == "Both API and MCP"

        # API route should be registered
        assert "/test/{name}:GET" in app.list_api_routes()

    def test_double_stack_tool_and_get(self):
        """@app.tool() + @app.get() without @app.common()."""
        app = ProdMCP("T")

        @app.tool(name="weather", description="Get weather")
        @app.get("/weather/{city}", tags=["weather"])
        def get_weather(city: str) -> dict:
            return {"city": city, "temp": 22.0}

        assert "weather" in app.list_tools()
        assert "/weather/{city}:GET" in app.list_api_routes()

    def test_function_is_not_modified(self):
        """Stacking decorators should not alter the function's behavior."""
        app = ProdMCP("T")

        @app.common(input_schema=InputA)
        @app.tool(name="pure")
        @app.get("/pure/{name}")
        def pure_fn(name: str) -> dict:
            return {"result": name}

        # Direct call should still work
        assert pure_fn("hello") == {"result": "hello"}


class TestCommonNotRequired:
    """@app.common() is optional — standalone decorators must work alone."""

    def test_tool_alone_with_inline_schemas(self):
        app = ProdMCP("T")

        @app.tool(name="standalone", input_schema=InputA, output_schema=OutputA)
        def standalone(name: str) -> dict:
            return {"result": name}

        meta = app.get_tool_meta("standalone")
        assert meta["input_schema"] is InputA

    def test_get_alone(self):
        app = ProdMCP("T")

        @app.get("/health")
        def health() -> dict:
            return {"status": "ok"}

        assert "/health:GET" in app.list_api_routes()

    def test_tool_alone_no_schemas(self):
        app = ProdMCP("T")

        @app.tool()
        def bare_tool() -> str:
            return "bare"

        assert "bare_tool" in app.list_tools()
        meta = app.get_tool_meta("bare_tool")
        assert meta["input_schema"] is None
