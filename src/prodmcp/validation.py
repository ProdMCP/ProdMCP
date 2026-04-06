"""Validation engine for ProdMCP.

Wraps handler functions with input/output validation.
"""

from __future__ import annotations

import inspect
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
    is_async = inspect.iscoroutinefunction(fn)

    if is_async:
        @wraps(fn)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            # Validate input
            # Bug F fix: guard on schema presence only, not kwargs truthiness.
            # The old `if input_schema and kwargs:` skipped validation when
            # kwargs={} (e.g. all-default-param handlers), missing required-field
            # checks and type constraints on optional fields.
            if input_schema is not None:
                validated_kwargs = _validate_input(kwargs, input_schema)
                kwargs = {**kwargs, **validated_kwargs}

            # Execute handler
            result = await fn(*args, **kwargs)

            # Validate output
            # E5 fix: use `is not None` not truthiness — matches the Bug-F fix on
            # input_schema above. A falsy schema like {} was previously silently skipped.
            if output_schema is not None:
                result = _validate_output(result, output_schema, strict)
            return result

        return async_wrapper
    else:
        @wraps(fn)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            # Validate input
            # Bug F fix: same as async path — guard on schema only.
            if input_schema is not None:
                validated_kwargs = _validate_input(kwargs, input_schema)
                kwargs = {**kwargs, **validated_kwargs}

            # Execute handler
            result = fn(*args, **kwargs)

            # Validate output
            if output_schema is not None:
                result = _validate_output(result, output_schema, strict)
            return result

        return sync_wrapper


def _validate_input(
    kwargs: dict[str, Any],
    schema: Type[BaseModel] | dict[str, Any],
) -> dict[str, Any]:
    """Validate input kwargs against a schema.

    Returns the validated data dict.

    Bug 8 fix: router.py now passes Pydantic body params as a named kwarg:
        kwargs = {"request": {"message": "hello"}}   # NOT {"message": "hello"}
    When the schema is a BaseModel and kwargs has a single key whose value is a
    plain dict, we first attempt validation against the *inner* dict.  If that
    succeeds we re-nest the result under the original key so downstream callers
    (dep_wrapper / _sig_wrapper) receive the correctly-keyed argument.
    """
    from pydantic import BaseModel as _BaseModel  # avoid circular at module level

    # Bug 8: detect the "named body param" layout and unwrap before validating.
    _body_key: str | None = None
    _body_data: dict[str, Any] | None = None
    if (
        isinstance(schema, type)
        and issubclass(schema, _BaseModel)
        and len(kwargs) == 1
    ):
        _only_key, _only_val = next(iter(kwargs.items()))
        if isinstance(_only_val, dict):
            # Heuristic: if the schema fields don't include _only_key but do
            # include at least one key from _only_val, the body was wrapped.
            schema_fields = set(schema.model_fields.keys())
            if _only_key not in schema_fields and schema_fields & set(_only_val.keys()):
                _body_key = _only_key
                _body_data = _only_val

    if _body_key is not None and _body_data is not None:
        try:
            validated = validate_data(_body_data, schema, direction="input")
            if isinstance(validated, dict):
                return {_body_key: schema(**_body_data)}  # return model instance keyed by param name
            if isinstance(validated, _BaseModel):
                return {_body_key: validated}
        except Exception:
            pass  # fall through to the standard path

    try:
        validated = validate_data(kwargs, schema, direction="input")
        if isinstance(validated, dict):
            return validated
        # B6 fix: handle case where validate_data returns a BaseModel instance.
        # The dead-code `return kwargs` fallback would silently bypass validation
        # entirely — instead surface the result correctly or raise.
        if isinstance(validated, BaseModel):
            return validated.model_dump()
        raise ProdMCPValidationError(
            f"Input validation returned unexpected type {type(validated).__name__}; "
            "expected a dict. This is likely a validation engine bug.",
            errors=[{
                "loc": [],
                "msg": f"Validator returned {type(validated).__name__} instead of dict",
                "type": "validation_error",
            }],
        )
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
