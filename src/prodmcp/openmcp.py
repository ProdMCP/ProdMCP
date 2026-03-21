"""OpenMCP specification generator.

Automatically produces a machine-readable OpenMCP JSON spec from
the ProdMCP registry.
"""

from __future__ import annotations

import json
from typing import Any, TYPE_CHECKING

from .schemas import extract_schema_ref, resolve_schema

if TYPE_CHECKING:
    from .app import ProdMCP


def generate_spec(app: ProdMCP) -> dict[str, Any]:
    """Generate the full OpenMCP specification from a ProdMCP app.

    Args:
        app: The ProdMCP application instance.

    Returns:
        A dict representing the OpenMCP JSON spec.
    """
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

    if tools:
        spec["tools"] = tools
    if prompts:
        spec["prompts"] = prompts
    if resources:
        spec["resources"] = resources
    if components.get("schemas") or components.get("securitySchemes"):
        spec["components"] = components

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

        # Security
        security_config = meta.get("security", [])
        if security_config:
            tool_spec["security"] = app._security_manager.generate_security_spec(
                security_config
            )

        # Middleware
        middleware = meta.get("middleware", [])
        if middleware:
            tool_spec["middleware"] = middleware

        # Tags
        tags = meta.get("tags")
        if tags:
            tool_spec["tags"] = sorted(tags) if isinstance(tags, set) else tags

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

        tags = meta.get("tags")
        if tags:
            prompt_spec["tags"] = sorted(tags) if isinstance(tags, set) else tags

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

        tags = meta.get("tags")
        if tags:
            resource_spec["tags"] = sorted(tags) if isinstance(tags, set) else tags

        resources[name] = resource_spec

    return resources


def spec_to_json(spec: dict[str, Any], indent: int = 2) -> str:
    """Serialize an OpenMCP spec to a JSON string."""
    return json.dumps(spec, indent=indent, default=str)
