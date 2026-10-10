"""The contract (openapi.json) as the tests read it: which operation a request is, and an
example of any schema, which the mock replies in tests/calls.py are made of."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nohead._generated.operations import OPERATIONS

SPEC: dict[str, Any] = json.loads((Path(__file__).parent.parent / "openapi.json").read_text())


def pointer(*parts: str) -> str:
    """A JSON pointer into the contract."""
    return "#/" + "/".join(part.replace("~", "~0").replace("/", "~1") for part in parts)


def at(path: str) -> tuple[str, Any]:
    """The value at a pointer, and where it is, following a `$ref` there."""
    value: Any = SPEC
    for part in path[2:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        value = value[int(part)] if isinstance(value, list) else value[part]
    return at(value["$ref"]) if "$ref" in value else (path, value)


@dataclass
class Parameter:
    name: str
    schema: dict[str, Any]
    schema_at: str
    """Where `schema` is in the contract."""


@dataclass
class Body:
    """A JSON body's schema."""

    schema: dict[str, Any]
    schema_at: str


@dataclass
class Route:
    id: str
    method: str
    pattern: re.Pattern[str]
    query: list[Parameter]
    body: Body | None
    """The request body, if the operation takes one."""
    body_required: bool
    status: int
    """The first success status."""
    response: Body


def _query(owner: dict[str, Any], path: str) -> list[Parameter]:
    found: list[Parameter] = []
    for index in range(len(owner.get("parameters", []))):
        where, parameter = at(f"{path}/parameters/{index}")
        if parameter["in"] == "query":
            found.append(Parameter(parameter["name"], parameter["schema"], f"{where}/schema"))
    return found


def _json(path: str) -> Body:
    where = f"{at(path)[0]}/content/application~1json/schema"
    return Body(at(where)[1], where)


def _route(operation_id: str, method: str, path: str) -> Route:
    item = SPEC["paths"][path]
    operation = item[method.lower()]
    item_at = pointer("paths", path)
    operation_at = pointer("paths", path, method.lower())
    status = next(code for code in operation["responses"] if code.startswith("2"))
    return Route(
        id=operation_id,
        method=method,
        pattern=re.compile("^" + re.sub(r"\{\w+\}", "[^/]+", path) + "$"),
        query=_query(item, item_at) + _query(operation, operation_at),
        body=_json(f"{operation_at}/requestBody") if "requestBody" in operation else None,
        body_required=operation.get("requestBody", {}).get("required", False),
        status=int(status),
        response=_json(f"{operation_at}/responses/{status}"),
    )


ROUTES = [_route(op, method, path) for op, (method, path) in OPERATIONS.items()]


def route_of(method: str, path: str) -> Route:
    for route in ROUTES:
        if route.method == method and route.pattern.match(path):
            return route
    raise AssertionError(f"No operation for {method} {path}")


def example(schema: dict[str, Any]) -> Any:
    """A value that matches `schema`: its example, constant, first enum value or default,
    else one built from its type, with every property (the first non-null type, the
    first of `oneOf` and `anyOf`)."""
    if "$ref" in schema:
        return example(at(schema["$ref"])[1])
    if "examples" in schema:
        return schema["examples"][0]
    if "const" in schema:
        return schema["const"]
    if "enum" in schema:
        return schema["enum"][0]
    if "default" in schema:
        return schema["default"]
    if "allOf" in schema:
        merged: dict[str, Any] = {}
        for part in schema["allOf"]:
            merged |= example(part)
        return merged
    if "oneOf" in schema or "anyOf" in schema:
        return example((schema.get("oneOf") or schema["anyOf"])[0])
    types = schema.get("type", [])
    types = types if isinstance(types, list) else [types]
    kind = next((t for t in types if t != "null"), types[0] if types else None)
    if kind == "object":
        return {name: example(sub) for name, sub in schema.get("properties", {}).items()}
    if kind == "array":
        return [example(schema.get("items", {}))] * max(schema.get("minItems", 1), 1)
    if kind == "string":
        return {"date-time": "2026-10-02T12:00:00Z", "date": "2026-10-02"}.get(
            schema.get("format", ""), "string"
        )
    if kind in ("integer", "number"):
        return schema.get("minimum", 1)
    if kind == "boolean":
        return False
    if kind == "null":
        return None
    return {}
