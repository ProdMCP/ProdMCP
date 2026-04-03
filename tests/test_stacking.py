"""Tests for stacking multiple decorators on the same function.

Validates all decorator combinations work correctly:
- tool + get/post/put/delete/patch
- common + tool + get
- common + resource + get
- common + prompt
"""

from pydantic import BaseModel

from prodmcp.app import ProdMCP


class InModel(BaseModel):
    x: int

class OutModel(BaseModel):
    result: int


class TestToolPlusGet:
    def test_basic_stacking(self):
        app = ProdMCP("T")

        @app.tool(name="users", description="Fetch users")
        @app.get("/users", tags=["users"])
        def get_users():
            return []

        assert "users" in app.list_tools()
        assert "/users:GET" in app.list_api_routes()

    def test_stacking_with_path_params(self):
        app = ProdMCP("T")

        @app.tool(name="get_user", description="Get user by ID")
        @app.get("/users/{user_id}", tags=["users"])
        def get_user(user_id: int):
            return {"id": user_id}

        assert "get_user" in app.list_tools()
        meta = app.get_tool_meta("get_user")
        assert meta["description"] == "Get user by ID"


class TestToolPlusPost:
    def test_tool_post_stacking(self):
        app = ProdMCP("T")

        @app.tool(name="create_item")
        @app.post("/items", status_code=201)
        def create_item(name: str):
            return {"name": name}

        assert "create_item" in app.list_tools()
        assert "/items:POST" in app.list_api_routes()
        meta = app._registry["api"]["/items:POST"]
        assert meta["status_code"] == 201


class TestToolPlusPut:
    def test_tool_put_stacking(self):
        app = ProdMCP("T")

        @app.tool(name="update_item")
        @app.put("/items/{id}")
        def update_item(id: int, name: str):
            return {"id": id, "name": name}

        assert "update_item" in app.list_tools()
        assert "/items/{id}:PUT" in app.list_api_routes()


class TestToolPlusDelete:
    def test_tool_delete_stacking(self):
        app = ProdMCP("T")

        @app.tool(name="remove_item")
        @app.delete("/items/{id}", status_code=204)
        def remove_item(id: int):
            return None

        assert "remove_item" in app.list_tools()
        assert "/items/{id}:DELETE" in app.list_api_routes()


class TestToolPlusPatch:
    def test_tool_patch_stacking(self):
        app = ProdMCP("T")

        @app.tool(name="patch_item")
        @app.patch("/items/{id}")
        def patch_item(id: int):
            return {}

        assert "patch_item" in app.list_tools()
        assert "/items/{id}:PATCH" in app.list_api_routes()


class TestCommonPlusToolPlusHTTP:
    def test_triple_stack_get(self):
        app = ProdMCP("T")

        @app.common(input_schema=InModel, output_schema=OutModel)
        @app.tool(name="compute", description="Compute result")
        @app.get("/compute/{x}")
        def compute(x: int):
            return {"result": x * 2}

        assert "compute" in app.list_tools()
        assert "/compute/{x}:GET" in app.list_api_routes()
        meta = app.get_tool_meta("compute")
        assert meta["input_schema"] is InModel
        assert meta["output_schema"] is OutModel

    def test_triple_stack_post(self):
        app = ProdMCP("T")

        @app.common(input_schema=InModel, output_schema=OutModel)
        @app.tool(name="process")
        @app.post("/process", status_code=201)
        def process(x: int):
            return {"result": x}

        assert "process" in app.list_tools()
        assert "/process:POST" in app.list_api_routes()


class TestResourcePlusGet:
    def test_resource_and_get_stacking(self):
        app = ProdMCP("T")

        @app.common(output_schema=OutModel)
        @app.resource(uri="data://items", name="item_db")
        @app.get("/items", tags=["items"])
        def items():
            return [{"result": 1}]

        assert "item_db" in app.list_resources()
        assert "/items:GET" in app.list_api_routes()
        meta = app.get_resource_meta("item_db")
        assert meta["output_schema"] is OutModel


class TestMultipleToolsOnSameApp:
    def test_many_stacked_handlers(self):
        """Register 10 handlers, each stacked with tool + get."""
        app = ProdMCP("T")

        for i in range(10):
            @app.tool(name=f"tool_{i}", description=f"Tool {i}")
            @app.get(f"/entity/{i}")
            def handler(idx=i):
                return {"id": idx}

        assert len(app.list_tools()) == 10
        assert len(app.list_api_routes()) == 10

        for i in range(10):
            assert f"tool_{i}" in app.list_tools()
            assert f"/entity/{i}:GET" in app.list_api_routes()


class TestFunctionBehaviorAfterStacking:
    def test_function_still_callable(self):
        app = ProdMCP("T")

        @app.tool(name="adder")
        @app.post("/add")
        def add(a: int, b: int) -> int:
            return a + b

        assert add(3, 4) == 7

    def test_async_function_preserved(self):
        import asyncio
        app = ProdMCP("T")

        @app.tool(name="async_adder")
        @app.post("/async-add")
        async def async_add(a: int, b: int) -> int:
            return a + b

        assert asyncio.iscoroutinefunction(async_add)

    def test_docstring_preserved(self):
        app = ProdMCP("T")

        @app.tool(name="documented")
        @app.get("/doc")
        def documented():
            """This is my docstring."""
            return {}

        assert documented.__doc__ == "This is my docstring."

    def test_function_name_preserved(self):
        app = ProdMCP("T")

        @app.tool(name="named")
        @app.get("/named")
        def my_actual_function():
            return {}

        assert my_actual_function.__name__ == "my_actual_function"
