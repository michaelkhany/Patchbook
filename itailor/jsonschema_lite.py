# iTailor - Copyright (c) 2026 Michael Bidollahkhani. All rights reserved. MIT License.
"""
A small JSON-schema validator (type, required, properties, items, enum,
additionalProperties, minimum/maximum, minLength/maxLength, minItems).

Enough to validate the structured replies iTailor asks a model for (plans,
understanding, tool arguments) without a dependency. Returns a list of
human-readable violations; an empty list means valid.
"""

from __future__ import annotations

from typing import Any

_TYPES = {
    "object": dict, "array": list, "string": str, "integer": int, "number": (int, float),
    "boolean": bool, "null": type(None),
}


def _type_ok(value: Any, expected: str) -> bool:
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    cls = _TYPES.get(expected)
    return cls is not None and isinstance(value, cls)


def validate(instance: Any, schema: dict, path: str = "$") -> list[str]:
    errors: list[str] = []
    if not isinstance(schema, dict):
        return errors
    expected = schema.get("type")
    if expected:
        types = expected if isinstance(expected, list) else [expected]
        if not any(_type_ok(instance, t) for t in types):
            errors.append(f"{path}: expected {'/'.join(types)}, got {type(instance).__name__}")
            return errors
    if "enum" in schema and instance not in schema["enum"]:
        errors.append(f"{path}: must be one of {schema['enum']!r}")
    if isinstance(instance, dict):
        props = schema.get("properties") or {}
        for key in schema.get("required") or []:
            if key not in instance:
                errors.append(f"{path}.{key}: required")
        for key, value in instance.items():
            if key in props:
                errors.extend(validate(value, props[key], f"{path}.{key}"))
            elif schema.get("additionalProperties") is False:
                errors.append(f"{path}.{key}: unexpected property")
    if isinstance(instance, list):
        items = schema.get("items")
        if "minItems" in schema and len(instance) < schema["minItems"]:
            errors.append(f"{path}: at least {schema['minItems']} item(s) required")
        if isinstance(items, dict):
            for index, value in enumerate(instance):
                errors.extend(validate(value, items, f"{path}[{index}]"))
    if isinstance(instance, str):
        if "minLength" in schema and len(instance) < schema["minLength"]:
            errors.append(f"{path}: shorter than {schema['minLength']}")
        if "maxLength" in schema and len(instance) > schema["maxLength"]:
            errors.append(f"{path}: longer than {schema['maxLength']}")
    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            errors.append(f"{path}: below minimum {schema['minimum']}")
        if "maximum" in schema and instance > schema["maximum"]:
            errors.append(f"{path}: above maximum {schema['maximum']}")
    return errors


def extract_json(text: str) -> Any:
    """The first JSON object or array in a model reply, fenced or bare."""
    import json
    import re

    s = str(text or "")
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", s, re.I)
    candidates = [fenced.group(1)] if fenced else []
    candidates.append(s)
    for candidate in candidates:
        candidate = candidate.strip()
        for opener, closer in (("{", "}"), ("[", "]")):
            start = candidate.find(opener)
            end = candidate.rfind(closer)
            if start != -1 and end > start:
                try:
                    return json.loads(candidate[start:end + 1])
                except Exception:  # noqa: BLE001
                    continue
    raise ValueError("no JSON object found in the reply")
