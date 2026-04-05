"""Tests for HTTP method decorators: @app.get(), @app.post(), etc.

These must have identical signatures to FastAPI's decorators.
"""

from pydantic import BaseModel

from prodmcp.app import ProdMCP


class UserOut(BaseModel):
    id: int
    name: str


class UserIn(BaseModel):
    name: str
    email: str


# ── Registration ─────────────────────────────────────────────────────

class TestGetDecorator:
    def test_registers_get_route(self):
        app = ProdMCP("T")

        @app.get("/items")
        def list_items():
            return []

        assert "/items:GET" in app.list_api_routes()

    def test_get_with_path_param(self):
        app = ProdMCP("T")

        @app.get("/items/{item_id}")
        def get_item(item_id: int):
            return {"id": item_id}

        meta = app._registry["api"]["/items/{item_id}:GET"]
        assert meta["path"] == "/items/{item_id}"
        assert meta["method"] == "GET"

    def test_get_default_status_200(self):
        app = ProdMCP("T")

        @app.get("/test")
        def handler():
            return {}

        meta = app._registry["api"]["/test:GET"]
        assert meta["status_code"] == 200

    def test_get_with_response_model(self):
        app = ProdMCP("T")

        @app.get("/users/{id}", response_model=UserOut)
        def get_user(id: int):
            return {"id": id, "name": "Alice"}

        meta = app._registry["api"]["/users/{id}:GET"]
        assert meta["response_model"] is UserOut

    def test_get_with_tags(self):
        app = ProdMCP("T")

        @app.get("/health", tags=["system", "monitoring"])
        def health():
            return {"ok": True}

        meta = app._registry["api"]["/health:GET"]
        assert meta["tags"] == ["system", "monitoring"]

    def test_get_deprecated(self):
        app = ProdMCP("T")

        @app.get("/old", deprecated=True)
        def old_endpoint():
            return {}

        meta = app._registry["api"]["/old:GET"]
        assert meta["deprecated"] is True

    def test_get_operation_id(self):
        app = ProdMCP("T")

        @app.get("/test", operation_id="test_operation")
        def handler():
            return {}

        meta = app._registry["api"]["/test:GET"]
        assert meta["operation_id"] == "test_operation"

    def test_get_include_in_schema(self):
        app = ProdMCP("T")

        @app.get("/internal", include_in_schema=False)
        def internal():
            return {}

        meta = app._registry["api"]["/internal:GET"]
        assert meta["include_in_schema"] is False


class TestPostDecorator:
    def test_registers_post_route(self):
        app = ProdMCP("T")

        @app.post("/items")
        def create_item():
            return {}

        assert "/items:POST" in app.list_api_routes()

    def test_post_default_status_201(self):
        app = ProdMCP("T")

        @app.post("/items")
        def create():
            return {}

        meta = app._registry["api"]["/items:POST"]
        assert meta["status_code"] == 201

    def test_post_custom_status(self):
        app = ProdMCP("T")

        @app.post("/items", status_code=200)
        def create():
            return {}

        meta = app._registry["api"]["/items:POST"]
        assert meta["status_code"] == 200

    def test_post_with_all_params(self):
        app = ProdMCP("T")

        @app.post(
            "/users",
            response_model=UserOut,
            status_code=201,
            tags=["users"],
            summary="Create a user",
            description="Creates a new user account",
            deprecated=False,
            operation_id="create_user",
        )
        def create_user(payload: UserIn):
            return {"id": 1, "name": payload.name}

        meta = app._registry["api"]["/users:POST"]
        assert meta["response_model"] is UserOut
        assert meta["status_code"] == 201
        assert meta["tags"] == ["users"]
        assert meta["summary"] == "Create a user"
        assert meta["description"] == "Creates a new user account"
        assert meta["operation_id"] == "create_user"


class TestPutDecorator:
    def test_registers_put_route(self):
        app = ProdMCP("T")

        @app.put("/items/{id}")
        def update(id: int):
            return {}

        assert "/items/{id}:PUT" in app.list_api_routes()

    def test_put_default_status_200(self):
        app = ProdMCP("T")

        @app.put("/items/{id}")
        def update(id: int):
            return {}

        meta = app._registry["api"]["/items/{id}:PUT"]
        assert meta["status_code"] == 200


class TestDeleteDecorator:
    def test_registers_delete_route(self):
        app = ProdMCP("T")

        @app.delete("/items/{id}")
        def remove(id: int):
            return None

        assert "/items/{id}:DELETE" in app.list_api_routes()

    def test_delete_default_status_204(self):
        app = ProdMCP("T")

        @app.delete("/items/{id}")
        def remove(id: int):
            return None

        meta = app._registry["api"]["/items/{id}:DELETE"]
        assert meta["status_code"] == 204


class TestPatchDecorator:
    def test_registers_patch_route(self):
        app = ProdMCP("T")

        @app.patch("/items/{id}")
        def patch(id: int):
            return {}

        assert "/items/{id}:PATCH" in app.list_api_routes()

    def test_patch_default_status_200(self):
        app = ProdMCP("T")

        @app.patch("/items/{id}")
        def patch(id: int):
            return {}

        meta = app._registry["api"]["/items/{id}:PATCH"]
        assert meta["status_code"] == 200


# ── Multiple routes on same path ──────────────────────────────────────

class TestMultipleMethodsSamePath:
    def test_get_and_post_on_same_path(self):
        app = ProdMCP("T")

        @app.get("/items")
        def list_items():
            return []

        @app.post("/items")
        def create_item():
            return {}

        assert "/items:GET" in app.list_api_routes()
        assert "/items:POST" in app.list_api_routes()

    def test_full_crud(self):
        app = ProdMCP("T")

        @app.get("/items")
        def list_items(): return []

        @app.post("/items")
        def create_item(): return {}

        @app.get("/items/{id}")
        def get_item(id: int): return {}

        @app.put("/items/{id}")
        def update_item(id: int): return {}

        @app.patch("/items/{id}")
        def patch_item(id: int): return {}

        @app.delete("/items/{id}")
        def delete_item(id: int): return None

        routes = app.list_api_routes()
        assert len(routes) == 6
        assert "/items:GET" in routes
        assert "/items:POST" in routes
        assert "/items/{id}:GET" in routes
        assert "/items/{id}:PUT" in routes
        assert "/items/{id}:PATCH" in routes
        assert "/items/{id}:DELETE" in routes


# ── Function preservation ──────────────────────────────────────────────

class TestFunctionPreservation:
    def test_decorator_returns_original_function(self):
        app = ProdMCP("T")

        @app.get("/test")
        def original():
            """My docstring."""
            return 42

        assert original() == 42
        assert original.__doc__ == "My docstring."

    def test_async_function_preserved(self):
        import asyncio
        app = ProdMCP("T")

        @app.get("/async")
        async def async_handler():
            return "async_result"

        assert asyncio.iscoroutinefunction(async_handler)

    def test_docstring_used_as_summary(self):
        app = ProdMCP("T")

        @app.get("/auto-summary")
        def handler():
            """This is the summary."""
            return {}

        meta = app._registry["api"]["/auto-summary:GET"]
        assert meta["summary"] == "This is the summary."

    def test_explicit_summary_overrides_docstring(self):
        app = ProdMCP("T")

        @app.get("/explicit", summary="Explicit summary")
        def handler():
            """This is the docstring."""
            return {}

        meta = app._registry["api"]["/explicit:GET"]
        assert meta["summary"] == "Explicit summary"
