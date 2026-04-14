"""OpenMCP specification generator.

Automatically produces a machine-readable OpenMCP JSON spec from
the ProdMCP registry.
"""

from __future__ import annotations

import json
from typing import Any, TYPE_CHECKING, Type

from .schemas import extract_schema_ref, resolve_schema
from .fastapi import _extract_output_description

if TYPE_CHECKING:
    from .app import ProdMCP


def generate_spec(app: "ProdMCP") -> dict[str, Any]:
    """Generate the full OpenMCP specification from a ProdMCP app.

    Args:
        app: The ProdMCP application instance.

    Returns:
        A dict representing the OpenMCP JSON spec.
    """
    # Bug 8 fix: generate_spec is in __all__ and callable directly.
    # Without _finalize_pending() the registry is empty if called before
    # app.run() or app.export_openmcp(), producing a silently empty spec.
    app._finalize_pending()

    components: dict[str, Any] = {"schemas": {}, "securitySchemes": {}}

    # Build tools section
    tools = _build_tools(app, components)

    # Build prompts section
    prompts = _build_prompts(app, components)

    # Build resources section
    resources = _build_resources(app, components)

    # Generate security schemes from security manager
    schemes = app._security_manager.generate_schemes_spec()
    components["securitySchemes"].update(schemes)

    # Clean up empty sections
    if not components["schemas"]:
        del components["schemas"]
    if not components["securitySchemes"]:
        del components["securitySchemes"]

    spec: dict[str, Any] = {
        "openmcp": "1.0.0",
        "info": {
            "title": app.name,
            "version": app.version,
        },
    }
    if app.description:
        spec["info"]["description"] = app.description
    
    if app.servers:
        spec["servers"] = app.servers

    if tools:
        spec["tools"] = tools
    if prompts:
        spec["prompts"] = prompts
    if resources:
        spec["resources"] = resources
    if components.get("schemas") or components.get("securitySchemes"):
        spec["components"] = components

    # Inject global security field (applies to ALL capabilities by default)
    if schemes:
        spec["security"] = [{name: []} for name in schemes]

    # Harden component schemas for scanner compliance (mirrors fastapi.py steps 4+5)
    _harden_openmcp_schemas(spec)

    return spec


def _build_tools(app: ProdMCP, components: dict[str, Any]) -> dict[str, Any]:
    """Build the tools section of the spec."""
    tools: dict[str, Any] = {}

    for name, meta in app._registry.get("tools", {}).items():
        tool_spec: dict[str, Any] = {}

        description = meta.get("description", "")
        if description:
            tool_spec["description"] = description

        # Input schema
        input_ref = extract_schema_ref(meta.get("input_schema"), components)
        if input_ref:
            tool_spec["input"] = input_ref

        # Output schema
        output_ref = extract_schema_ref(meta.get("output_schema"), components)
        if output_ref:
            tool_spec["output"] = output_ref

        # Output description — derived from the output model's docstring
        output_desc = _extract_output_description(meta.get("output_schema"))
        if output_desc and output_desc != "Successful Response":
            tool_spec["output_description"] = output_desc

        # Security
        security_config = meta.get("security", [])
        if security_config:
            tool_spec["security"] = app._security_manager.generate_security_spec(
                security_config
            )

        # Middleware — N3 fix: only include string names.
        # Middleware instances are not JSON-serializable; including them causes
        # json.dumps to silently emit their repr() via default=str, which is
        # meaningless in the spec context.
        middleware = meta.get("middleware", [])
        if middleware:
            serializable = [m for m in middleware if isinstance(m, str)]
            if serializable:
                tool_spec["middleware"] = serializable

        # Error handling (42Crunch / MCPcrunch compliance)
        from .fastapi import (
            ErrorDetail,
            ProdMCPHTTPValidationError,
        )

        error_handling: dict[str, Any] = {
            "406": extract_schema_ref(ErrorDetail, components),
            "415": extract_schema_ref(ErrorDetail, components),
            "422": extract_schema_ref(ProdMCPHTTPValidationError, components),
            "429": extract_schema_ref(ErrorDetail, components),
            "default": extract_schema_ref(ErrorDetail, components),
        }
        if security_config:
            error_handling["401"] = extract_schema_ref(ErrorDetail, components)
            error_handling["403"] = extract_schema_ref(ErrorDetail, components)

        tool_spec["error_handling"] = error_handling

        tools[name] = tool_spec

    return tools


def _build_prompts(app: ProdMCP, components: dict[str, Any]) -> dict[str, Any]:
    """Build the prompts section of the spec."""
    prompts: dict[str, Any] = {}

    for name, meta in app._registry.get("prompts", {}).items():
        prompt_spec: dict[str, Any] = {}

        description = meta.get("description", "")
        if description:
            prompt_spec["description"] = description

        input_ref = extract_schema_ref(meta.get("input_schema"), components)
        if input_ref:
            prompt_spec["input"] = input_ref

        output_ref = extract_schema_ref(meta.get("output_schema"), components)
        if output_ref:
            prompt_spec["output"] = output_ref

        # Output description
        output_desc = _extract_output_description(meta.get("output_schema"))
        if output_desc and output_desc != "Successful Response":
            prompt_spec["output_description"] = output_desc

        tags = meta.get("tags")
        if tags:
            prompt_spec["tags"] = sorted(tags) if isinstance(tags, set) else tags

        # Security (mirrors tool security injection)
        security_config = meta.get("security", [])
        if security_config:
            prompt_spec["security"] = app._security_manager.generate_security_spec(
                security_config
            )

        # Standard errors for prompts
        from .fastapi import ErrorDetail, ProdMCPHTTPValidationError

        error_handling: dict[str, Any] = {
            "406": extract_schema_ref(ErrorDetail, components),
            "415": extract_schema_ref(ErrorDetail, components),
            "422": extract_schema_ref(ProdMCPHTTPValidationError, components),
            "429": extract_schema_ref(ErrorDetail, components),
            "default": extract_schema_ref(ErrorDetail, components),
        }
        if security_config:
            error_handling["401"] = extract_schema_ref(ErrorDetail, components)
            error_handling["403"] = extract_schema_ref(ErrorDetail, components)

        prompt_spec["error_handling"] = error_handling

        prompts[name] = prompt_spec

    return prompts


def _build_resources(app: ProdMCP, components: dict[str, Any]) -> dict[str, Any]:
    """Build the resources section of the spec."""
    resources: dict[str, Any] = {}

    for name, meta in app._registry.get("resources", {}).items():
        resource_spec: dict[str, Any] = {}

        description = meta.get("description", "")
        if description:
            resource_spec["description"] = description

        uri = meta.get("uri", "")
        if uri:
            resource_spec["uri"] = uri

        output_ref = extract_schema_ref(meta.get("output_schema"), components)
        if output_ref:
            resource_spec["output"] = output_ref

        # Output description
        output_desc = _extract_output_description(meta.get("output_schema"))
        if output_desc and output_desc != "Successful Response":
            resource_spec["output_description"] = output_desc

        tags = meta.get("tags")
        if tags:
            resource_spec["tags"] = sorted(tags) if isinstance(tags, set) else tags

        # Security
        security_config = meta.get("security", [])
        if security_config:
            resource_spec["security"] = app._security_manager.generate_security_spec(
                security_config
            )

        # Standard errors for resources (no 415/422 as GET has no body)
        from .fastapi import ErrorDetail

        error_handling: dict[str, Any] = {
            "406": extract_schema_ref(ErrorDetail, components),
            "429": extract_schema_ref(ErrorDetail, components),
            "default": extract_schema_ref(ErrorDetail, components),
        }
        if security_config:
            error_handling["401"] = extract_schema_ref(ErrorDetail, components)
            error_handling["403"] = extract_schema_ref(ErrorDetail, components)

        resource_spec["error_handling"] = error_handling

        resources[name] = resource_spec

    return resources


def _warn_on_unserializable(obj: Any) -> Any:
    """Custom JSON ``default`` that warns before stringifying non-serializable values.

    C7 fix: ``default=str`` silently embeds garbage like
    ``"<class 'prodmcp.security.http.HTTPBearer'>"`` in the spec with no
    indication that something is wrong.  This wrapper emits a ``UserWarning``
    first so developers see the problem rather than getting a silently broken spec.
    """
    import warnings
    warnings.warn(
        f"spec_to_json: non-JSON-serializable value of type "
        f"{type(obj).__name__!r} found in the OpenMCP spec; converting to its "
        f"string representation {str(obj)!r:.80}. "
        "This usually indicates a middleware instance or Pydantic model class "
        "appearing in the spec dict. Check your schema/middleware configuration.",
        UserWarning,
        stacklevel=4,
    )
    return str(obj)


def spec_to_json(spec: dict[str, Any], indent: int = 2) -> str:
    """Serialize an OpenMCP spec to a JSON string."""
    return json.dumps(spec, indent=indent, default=_warn_on_unserializable)


def _harden_openmcp_schemas(spec: dict[str, Any]) -> None:
    """Harden component schemas in an OpenMCP spec for scanner compliance.

    Mirrors the FastAPI bridge steps 4+5:
      4. Set ``additionalProperties: false`` on object schemas that have
         properties but don't use combining operations.
      5. Set ``additionalProperties: false`` on property-level anyOf/oneOf
         where all sub-schemas are primitives (Pydantic's Optional pattern).
    """
    schemas = spec.get("components", {}).get("schemas", {})

    # Step 4: top-level object schemas
    for comp_schema in schemas.values():
        if (
            isinstance(comp_schema, dict)
            and comp_schema.get("type") == "object"
            and "properties" in comp_schema
            and "additionalProperties" not in comp_schema
            and "allOf" not in comp_schema
            and "anyOf" not in comp_schema
            and "oneOf" not in comp_schema
        ):
            comp_schema["additionalProperties"] = False

    # Step 5: nested anyOf/oneOf primitives
    from .fastapi import _harden_nested_anyof
    _harden_nested_anyof(spec)

