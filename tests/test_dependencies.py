"""Tests for the dependency injection system."""

import pytest

from prodmcp.dependencies import Depends, resolve_dependencies


# ── Simple dependencies ────────────────────────────────────────────────


def get_user(context):
    return context.get("user", {"id": "anonymous"})


def get_db(context):
    return context.get("db", "default_db")


async def get_async_config(context):
    return context.get("config", {"debug": False})


# ── Nested dependency ──────────────────────────────────────────────────


def get_user_role(context, user=Depends(get_user)):
    return user.get("role", "viewer")


# ── Tests ──────────────────────────────────────────────────────────────


class TestDepends:
    def test_repr(self):
        dep = Depends(get_user)
        assert "get_user" in repr(dep)


class TestResolveDependencies:
    @pytest.mark.asyncio
    async def test_simple_dependency(self):
        def handler(user=Depends(get_user)):
            return user

        context = {"user": {"id": "alice", "role": "admin"}}
        resolved = await resolve_dependencies(handler, context)
        assert resolved["user"]["id"] == "alice"

    @pytest.mark.asyncio
    async def test_multiple_dependencies(self):
        def handler(user=Depends(get_user), db=Depends(get_db)):
            return user, db

        context = {"user": {"id": "bob"}, "db": "prod_db"}
        resolved = await resolve_dependencies(handler, context)
        assert resolved["user"]["id"] == "bob"
        assert resolved["db"] == "prod_db"

    @pytest.mark.asyncio
    async def test_async_dependency(self):
        def handler(config=Depends(get_async_config)):
            return config

        context = {"config": {"debug": True}}
        resolved = await resolve_dependencies(handler, context)
        assert resolved["config"]["debug"] is True

    @pytest.mark.asyncio
    async def test_nested_dependency(self):
        def handler(role=Depends(get_user_role)):
            return role

        context = {"user": {"id": "alice", "role": "admin"}}
        resolved = await resolve_dependencies(handler, context)
        assert resolved["role"] == "admin"

    @pytest.mark.asyncio
    async def test_override(self):
        def handler(user=Depends(get_user)):
            return user

        resolved = await resolve_dependencies(
            handler, {}, overrides={"user": {"id": "override"}}
        )
        assert resolved["user"]["id"] == "override"

    @pytest.mark.asyncio
    async def test_caching(self):
        call_count = 0

        def counter_dep(context):
            nonlocal call_count
            call_count += 1
            return call_count

        def handler(a=Depends(counter_dep), b=Depends(counter_dep)):
            return a, b

        context = {}
        resolved = await resolve_dependencies(handler, context)
        # Same dep callable with use_cache=True → should be called once
        assert resolved["a"] == resolved["b"]
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_no_cache(self):
        call_count = 0

        def counter_dep(context):
            nonlocal call_count
            call_count += 1
            return call_count

        dep_no_cache = Depends(counter_dep, use_cache=False)

        def handler(a=dep_no_cache, b=dep_no_cache):
            return a, b

        context = {}
        resolved = await resolve_dependencies(handler, context)
        assert resolved["a"] != resolved["b"]

    @pytest.mark.asyncio
    async def test_no_depends_params_skipped(self):
        def handler(x: int = 5, y: str = "hello"):
            return x, y

        resolved = await resolve_dependencies(handler, {})
        # No Depends() defaults → nothing resolved
        assert resolved == {}
