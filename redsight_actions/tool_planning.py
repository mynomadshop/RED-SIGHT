"""Pure helpers for mapping RED-SIGHT tools to provider-native function calls."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from typing import Any


def parameter_schema(specification: str) -> dict[str, Any]:
    """Translate a compact gateway parameter contract into JSON Schema."""
    properties: dict[str, Any] = {}
    required: list[str] = []
    for raw_field in str(specification or "").split(","):
        field = raw_field.strip()
        if not field or ":" not in field:
            continue
        raw_name, raw_type = field.split(":", 1)
        optional = raw_name.strip().endswith("?")
        name = raw_name.strip().removesuffix("?")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            continue
        type_hint = raw_type.strip().lower()
        if "list" in type_hint or "array" in type_hint:
            schema: dict[str, Any] = {"type": "array", "items": {"type": "object"}}
            if "str" in type_hint:
                schema["items"] = {"type": "string"}
        elif "dict" in type_hint or "json" in type_hint or "object" in type_hint:
            schema = {"type": "object"}
        elif "bool" in type_hint:
            schema = {"type": "boolean"}
        elif "int" in type_hint:
            schema = {"type": "integer"}
        elif "float" in type_hint or "number" in type_hint:
            schema = {"type": "number"}
        else:
            schema = {"type": "string"}
        maximum = re.search(r"<=\s*(\d+)", type_hint)
        minimum = re.search(r">=\s*(\d+)", type_hint)
        if maximum and schema["type"] in {"integer", "number"}:
            schema["maximum"] = int(maximum.group(1))
        if minimum and schema["type"] in {"integer", "number"}:
            schema["minimum"] = int(minimum.group(1))
        properties[name] = schema
        if not optional:
            required.append(name)
    result: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        result["required"] = required
    return result


def provider_tool_name(tool: str) -> str:
    """Encode dotted gateway names for providers that reject dots."""
    return tool.replace(".", "__")


def build_agent_tool_schemas(
    tool_specs: Mapping[str, Mapping[str, Any]],
    *,
    exclude: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Return native function definitions for all agent-allowed tools."""
    excluded = exclude or set()
    return [
        {
            "type": "function",
            "function": {
                "name": provider_tool_name(name),
                "description": f"RED-SIGHT tool `{name}`. {spec['description']}",
                "parameters": parameter_schema(str(spec.get("params", ""))),
            },
        }
        for name, spec in tool_specs.items()
        if spec.get("agent") and name not in excluded
    ]


def decode_native_tool_steps(
    raw: str,
    tool_specs: Mapping[str, Mapping[str, Any]],
    *,
    agent_allowed: Callable[[str], bool],
    requires_approval: Callable[[str], bool],
    exclude: set[str] | None = None,
) -> tuple[list[dict[str, Any]], str] | None:
    """Decode provider-native function calls into the governed plan format."""
    candidate = str(raw or "").strip()
    candidate = re.sub(r"^```(?:json)?\s*", "", candidate)
    candidate = re.sub(r"\s*```$", "", candidate)
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict) or not isinstance(parsed.get("tool_calls"), list):
        return None

    encoded_names = {
        provider_tool_name(name): name
        for name, spec in tool_specs.items()
        if spec.get("agent")
    }
    excluded = exclude or set()
    steps = []
    for call in parsed["tool_calls"][:8]:
        if not isinstance(call, dict):
            continue
        function = call.get("function")
        if not isinstance(function, dict):
            continue
        requested = str(function.get("name") or "")
        tool = encoded_names.get(requested, requested)
        if tool in excluded or not agent_allowed(tool):
            continue
        arguments = function.get("arguments", {})
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments or "{}")
            except json.JSONDecodeError:
                arguments = {}
        if not isinstance(arguments, dict):
            arguments = {}
        steps.append(
            {
                "tool": tool,
                "params": arguments,
                "reason": "Selected through native provider tool calling.",
                "requires_approval": requires_approval(tool),
            }
        )
    return steps, str(parsed.get("content") or "")[:1_000]
