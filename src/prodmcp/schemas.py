"""Schema engine for ProdMCP.

Handles resolution, validation, and extraction of Pydantic models
and raw JSON Schema dictionaries.
"""

from __future__ import annotations

import logging
from typing import Any, Type

from pydantic import BaseModel, ValidationError

from .exceptions import ProdMCPValidationError

logger = logging.getLogger(__name__)


def resolve_schema(schema: Type[BaseModel] | dict[str, Any] | None) -> dict[str, Any] | None:
    """Resolve a Pydantic model or raw JSON Schema dict into a JSON Schema dict.

    Args:
        schema: A Pydantic BaseModel subclass, a raw JSON Schema dict, or None.

    Returns:
        A JSON Schema dictionary, or None if schema is None.
    """
    if schema is None:
        return None
    if isinstance(schema, dict):
        return schema
    if isinstance(schema, type) and issubclass(schema, BaseModel):
        return schema.model_json_schema()
    raise TypeError(
        f"Schema must be a Pydantic BaseModel subclass or a dict, got {type(schema)}"
    )


def validate_data(
    data: Any,
    schema: Type[BaseModel] | dict[str, Any] | None,
    *,
    direction: str = "input",
) -> Any:
    """Validate data against a schema.

    For Pydantic models, uses model_validate. For raw JSON Schema dicts,
    performs structural validation.

    Args:
        data: The data to validate.
        schema: The schema to validate against.
        direction: 'input' or 'output' — used in error messages.

    Returns:
        The validated (and possibly coerced) data.

    Raises:
        ProdMCPValidationError: If validation fails.
    """
    if schema is None:
        return data

    if isinstance(schema, type) and issubclass(schema, BaseModel):
        return _validate_pydantic(data, schema, direction)

    if isinstance(schema, dict):
        return _validate_json_schema(data, schema, direction)

    raise TypeError(f"Unsupported schema type: {type(schema)}")


def _validate_pydantic(
    data: Any, model: Type[BaseModel], direction: str
) -> Any:
    """Validate data using a Pydantic model."""
    try:
        if isinstance(data, dict):
            validated = model.model_validate(data)
        elif isinstance(data, model):
            validated = data
        else:
            validated = model.model_validate(data)
        return validated.model_dump()
    except ValidationError as exc:
        errors = [
            {
                "loc": list(e["loc"]),
                "msg": e["msg"],
                "type": e["type"],
            }
            for e in exc.errors()
        ]
        raise ProdMCPValidationError(
            f"{direction.capitalize()} validation failed: {exc.error_count()} error(s)",
            errors=errors,
        ) from exc


def _validate_json_schema(
    data: Any, schema: dict[str, Any], direction: str
) -> Any:
    """Validate data against a raw JSON Schema dict.

    Performs basic structural validation for object-type schemas.
    """
    schema_type = schema.get("type")
    if schema_type == "object":
        if not isinstance(data, dict):
            raise ProdMCPValidationError(
                f"{direction.capitalize()} validation failed: expected object, got {type(data).__name__}",
                errors=[{"loc": [], "msg": "expected object", "type": "type_error"}],
            )
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        errors: list[dict[str, Any]] = []
        for field_name in required:
            if field_name not in data:
                errors.append({
                    "loc": [field_name],
                    "msg": "field required",
                    "type": "missing",
                })
        for field_name, field_schema in properties.items():
            if field_name in data:
                expected_type = field_schema.get("type")
                if expected_type and not _check_json_type(data[field_name], expected_type):
                    errors.append({
                        "loc": [field_name],
                        "msg": f"expected {expected_type}",
                        "type": "type_error",
                    })
        if errors:
            raise ProdMCPValidationError(
                f"{direction.capitalize()} validation failed: {len(errors)} error(s)",
                errors=errors,
            )
    return data


def _check_json_type(value: Any, expected: str) -> bool:
    """Check if a Python value matches a JSON Schema type string."""
    type_map: dict[str, tuple[type, ...]] = {
        "string": (str,),
        "integer": (int,),
        "number": (int, float),
        "boolean": (bool,),
        "array": (list,),
        "object": (dict,),
    }
    allowed = type_map.get(expected)
    if allowed is None:
        return True  # Unknown type — skip check
    # In JSON, booleans are not numbers
    if expected in ("integer", "number") and isinstance(value, bool):
        return False
    return isinstance(value, allowed)


def _rewrite_refs(obj: Any) -> None:
    """Recursively rewrite ``#/$defs/X`` refs to ``#/components/schemas/X``.

    Pydantic v2 ``model_json_schema()`` places nested model definitions
    under ``$defs`` and references them via ``#/$defs/ModelName``.  When
    we hoist those definitions into ``components.schemas``, the ``$ref``
    pointers must be rewritten to match.
    """
    if isinstance(obj, dict):
        if "$ref" in obj and isinstance(obj["$ref"], str):
            obj["$ref"] = obj["$ref"].replace("#/$defs/", "#/components/schemas/")
        for value in obj.values():
            _rewrite_refs(value)
    elif isinstance(obj, list):
        for item in obj:
            _rewrite_refs(item)


def extract_schema_ref(
    schema: Type[BaseModel] | dict[str, Any] | None,
    components: dict[str, Any],
) -> dict[str, Any] | None:
    """Extract a schema as a $ref into components, or return inline JSON Schema.

    For Pydantic models, adds the model to components.schemas and returns a $ref.
    For raw dicts, returns the dict inline.

    Args:
        schema: The schema to extract.
        components: The components dict to populate (mutated in place).

    Returns:
        A $ref dict, an inline schema, or None.
    """
    if schema is None:
        return None

    if isinstance(schema, type) and issubclass(schema, BaseModel):
        name = schema.__name__
        json_schema = schema.model_json_schema()
        # Extract $defs if present (Pydantic v2 nests referenced models)
        defs = json_schema.pop("$defs", {})
        # Rewrite $ref paths from #/$defs/X to #/components/schemas/X
        _rewrite_refs(json_schema)
        for def_name, def_schema in defs.items():
            _rewrite_refs(def_schema)
            components.setdefault("schemas", {})[def_name] = def_schema
        components.setdefault("schemas", {})[name] = json_schema
        return {"$ref": f"#/components/schemas/{name}"}

    if isinstance(schema, dict):
        return schema

    return None
