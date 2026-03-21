"""Tests for the validation engine."""

import pytest
from pydantic import BaseModel

from prodmcp.exceptions import ProdMCPValidationError
from prodmcp.validation import create_validated_handler


# ── Fixtures ───────────────────────────────────────────────────────────


class InputModel(BaseModel):
    x: int
    y: int


class OutputModel(BaseModel):
    result: int


# ── Sync handler tests ─────────────────────────────────────────────────


class TestSyncValidation:
    def test_no_schema(self):
        def handler(a=1, b=2):
            return a + b

        wrapped = create_validated_handler(handler)
        assert wrapped(a=3, b=4) == 7

    def test_input_validation_passes(self):
        def handler(x=0, y=0):
            return {"result": x + y}

        wrapped = create_validated_handler(handler, input_schema=InputModel)
        result = wrapped(x=3, y=4)
        assert result["result"] == 7

    def test_input_validation_fails(self):
        def handler(x=0, y=0):
            return {"result": x + y}

        wrapped = create_validated_handler(handler, input_schema=InputModel)
        with pytest.raises(ProdMCPValidationError):
            wrapped(x="not_int", y=4)

    def test_output_validation_strict(self):
        def handler(x=0, y=0):
            return {"wrong_key": x + y}

        wrapped = create_validated_handler(
            handler, output_schema=OutputModel, strict=True
        )
        with pytest.raises(ProdMCPValidationError):
            wrapped(x=3, y=4)

    def test_output_validation_non_strict(self):
        def handler(x=0, y=0):
            return {"wrong_key": x + y}

        wrapped = create_validated_handler(
            handler, output_schema=OutputModel, strict=False
        )
        # Should not raise, but return original result
        result = wrapped(x=3, y=4)
        assert result["wrong_key"] == 7

    def test_output_validation_passes(self):
        def handler(x=0, y=0):
            return {"result": x + y}

        wrapped = create_validated_handler(
            handler, output_schema=OutputModel, strict=True
        )
        result = wrapped(x=3, y=4)
        assert result["result"] == 7


# ── Async handler tests ───────────────────────────────────────────────


class TestAsyncValidation:
    @pytest.mark.asyncio
    async def test_async_handler(self):
        async def handler(x=0, y=0):
            return {"result": x + y}

        wrapped = create_validated_handler(
            handler, input_schema=InputModel, output_schema=OutputModel
        )
        result = await wrapped(x=3, y=4)
        assert result["result"] == 7

    @pytest.mark.asyncio
    async def test_async_input_fail(self):
        async def handler(x=0, y=0):
            return {"result": x + y}

        wrapped = create_validated_handler(handler, input_schema=InputModel)
        with pytest.raises(ProdMCPValidationError):
            await wrapped(x="bad", y=4)
