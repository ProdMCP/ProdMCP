"""Validation engine for ProdMCP.

Wraps handler functions with input/output validation.
"""

from __future__ import annotations

import asyncio
import logging
from functools import wraps
from typing import Any, Callable, Type

from pydantic import BaseModel

from .exceptions import ProdMCPValidationError
from .schemas import validate_data

logger = logging.getLogger(__name__)


def create_validated_handler(
    fn: Callable[..., Any],
    *,
    input_schema: Type[BaseModel] | dict[str, Any] | None = None,
    output_schema: Type[BaseModel] | dict[str, Any] | None = None,
    strict: bool = True,
) -> Callable[..., Any]:
    """Wrap a handler function with input/output validation.

    Args:
        fn: The original handler function.
        input_schema: Pydantic model or JSON Schema dict for input validation.
        output_schema: Pydantic model or JSON Schema dict for output validation.
        strict: If True, output validation errors are raised.
                If False, output validation errors are logged as warnings.

    Returns:
        A wrapped function that validates inputs and outputs.
    """
    is_async = asyncio.iscoroutinefunction(fn)

    if is_async:
        @wraps(fn)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            # Validate input
            if input_schema and kwargs:
                validated_kwargs = _validate_input(kwargs, input_schema)
                kwargs = {**kwargs, **validated_kwargs}

            # Execute handler
            result = await fn(*args, **kwargs)

            # Validate output
            if output_schema:
                result = _validate_output(result, output_schema, strict)
            return result

        return async_wrapper
    else:
        @wraps(fn)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            # Validate input
            if input_schema and kwargs:
                validated_kwargs = _validate_input(kwargs, input_schema)
                kwargs = {**kwargs, **validated_kwargs}

            # Execute handler
            result = fn(*args, **kwargs)

            # Validate output
            if output_schema:
                result = _validate_output(result, output_schema, strict)
            return result

        return sync_wrapper


def _validate_input(
    kwargs: dict[str, Any],
    schema: Type[BaseModel] | dict[str, Any],
) -> dict[str, Any]:
    """Validate input kwargs against a schema.

    Returns the validated data dict.
    """
    try:
        validated = validate_data(kwargs, schema, direction="input")
        if isinstance(validated, dict):
            return validated
        return kwargs
    except ProdMCPValidationError:
        raise
    except Exception as exc:
        raise ProdMCPValidationError(
            f"Input validation error: {exc}",
            errors=[{"loc": [], "msg": str(exc), "type": "validation_error"}],
        ) from exc


def _validate_output(
    result: Any,
    schema: Type[BaseModel] | dict[str, Any],
    strict: bool,
) -> Any:
    """Validate output against a schema.

    In strict mode, raises on failure. In non-strict mode, logs a warning.
    """
    try:
        data = result
        if isinstance(result, BaseModel):
            data = result.model_dump()
        validated = validate_data(data, schema, direction="output")
        return validated
    except ProdMCPValidationError:
        if strict:
            raise
        logger.warning(
            "Output validation failed (non-strict mode): %s",
            result,
            exc_info=True,
        )
        return result
    except Exception as exc:
        if strict:
            raise ProdMCPValidationError(
                f"Output validation error: {exc}",
                errors=[{"loc": [], "msg": str(exc), "type": "validation_error"}],
            ) from exc
        logger.warning("Output validation error (non-strict): %s", exc)
        return result
