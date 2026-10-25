"""The contract (openapi.json) as the tests read it: which operation a request is, whether a
request or a reply matches it (every test's mock transport checks both, tests/conftest.py),
and an example of any schema, which the mock replies and fixtures are made of."""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

import httpx
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

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
    responses: dict[int, str]
    """Where each documented status's JSON schema is in the contract."""


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
        responses={
            int(code): _json(f"{operation_at}/responses/{code}").schema_at
            for code in operation["responses"]
        },
    )


ROUTES = [_route(op, method, path) for op, (method, path) in OPERATIONS.items()]


def route_of(method: str, path: str) -> Route:
    for route in ROUTES:
        if route.method == method and route.pattern.match(path):
            return route
    raise AssertionError(f"No operation for {method} {path}")


CONTRACT = "urn:nohead:openapi.json"
REGISTRY = Registry().with_resource(
    CONTRACT, Resource.from_contents(SPEC, default_specification=DRAFT202012)
)


@cache
def _validator(pointer: str) -> Draft202012Validator:
    return Draft202012Validator({"$ref": CONTRACT + pointer}, registry=REGISTRY)


def errors(pointer: str, value: Any) -> list[str]:
    """The errors of `value` against the schema at `pointer` in the contract."""
    return [error.message for error in _validator(pointer).iter_errors(value)]


def query_values(url: httpx.URL, params: list[Parameter]) -> dict[str, Any]:
    """A request's query parameters by name, as their schemas read them: `filter[a][b]=v`
    nests, and numbers and booleans are parsed when declared."""
    types = {p.name: p.schema.get("type") for p in params}
    values: dict[str, Any] = {}
    for key, value in url.params.multi_items():
        name, *path = [part for part in re.split(r"[\[\]]+", key) if part]
        if path:
            node = values.setdefault(name, {})
            for part in path[:-1]:
                node = node.setdefault(part, {})
            node[path[-1]] = value
        elif types.get(name) in ("integer", "number") and re.fullmatch(r"-?\d+(\.\d+)?", value):
            values[name] = float(value) if "." in value else int(value)
        elif types.get(name) == "boolean" and value in ("true", "false"):
            values[name] = value == "true"
        else:
            values[name] = value
    return values


@cache
def declared_headers(operation: str) -> frozenset[str]:
    """The header parameters an operation declares, lowercased."""
    method, path = OPERATIONS[operation]
    owners = [pointer("paths", path), pointer("paths", path, method.lower())]
    found: set[str] = set()
    for owner in owners:
        for index in range(len(at(owner)[1].get("parameters", []))):
            parameter = at(f"{owner}/parameters/{index}")[1]
            if parameter["in"] == "header":
                found.add(parameter["name"].lower())
    return frozenset(found)


# Headers that some operations declare and others don't.
OPTIONAL_HEADERS = {"idempotency-key", "if-match", "nohead-change-note"}


def route_of_request(request: httpx.Request) -> Route:
    """The operation a request is, by its path as sent (`%2F` in an ID stays in it)."""
    return route_of(request.method, request.url.raw_path.decode().partition("?")[0])


def check_request(request: httpx.Request) -> Route:
    """Asserts that a request matches its operation: method and path, declared headers,
    declared query parameters and their values, and the JSON body. Returns the operation."""
    route = route_of_request(request)
    extra = (OPTIONAL_HEADERS & set(request.headers)) - declared_headers(route.id)
    assert not extra, f"{route.id} sends undeclared headers {extra}"
    keys = {key.split("[", 1)[0] for key in request.url.params}
    declared = {p.name for p in route.query}
    assert keys <= declared, f"{route.id} sends undeclared query parameters {keys - declared}"
    values = query_values(request.url, route.query)
    for param in route.query:
        if param.name in values:
            problems = errors(param.schema_at, values[param.name])
            assert problems == [], f"{route.id} {param.name}: {problems}"
    if request.content:
        assert route.body is not None, f"{route.id} takes no body"
        problems = errors(route.body.schema_at, json.loads(request.content))
        assert problems == [], f"{route.id} body: {problems}"
    else:
        assert not route.body_required, f"{route.id} needs a body"
    return route


ERROR = pointer("components", "schemas", "Error")


def check_reply(route: Route, response: httpx.Response) -> None:
    """Asserts that a reply matches what its operation documents for its status. An error
    status the operation doesn't document (a 500, a gateway's 502) is still the API's
    error envelope."""
    where = route.responses.get(response.status_code)
    if where is None:
        assert response.status_code >= 400, f"{route.id} documents no {response.status_code}"
        where = ERROR
    assert "json" in response.headers.get("content-type", ""), (
        f"The {route.id} reply is not JSON: build it from the contract, or mark it raw()"
    )
    problems = errors(where, response.json())
    assert problems == [], (
        f"The {route.id} {response.status_code} reply does not match the contract: {problems}. "
        "Build it from the contract's example (tests/spec.py, example_of), or mark it raw() "
        "if it breaks the contract on purpose."
    )


def example(schema: dict[str, Any], variant: int = 0) -> Any:
    """A value that matches `schema`: its example, constant, first enum value or default,
    else one built from its type, with every property (the first non-null type). Of a
    `oneOf` or `anyOf`, it is the variant numbered `variant` (counting round), so the
    examples numbered 0 to VARIANTS - 1 take each union's every variant."""
    if "$ref" in schema:
        return example(at(schema["$ref"])[1], variant)
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
            merged |= example(part, variant)
        return merged
    if "oneOf" in schema or "anyOf" in schema:
        options = schema.get("oneOf") or schema["anyOf"]
        return example(options[variant % len(options)], variant)
    types = schema.get("type", [])
    types = types if isinstance(types, list) else [types]
    kind = next((t for t in types if t != "null"), types[0] if types else None)
    if kind == "object":
        return {name: example(sub, variant) for name, sub in schema.get("properties", {}).items()}
    if kind == "array":
        return [example(schema.get("items", {}), variant)] * max(schema.get("minItems", 1), 1)
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


def _widest(value: Any) -> int:
    """The most variants of any `oneOf` or `anyOf` in the contract."""
    if isinstance(value, dict):
        own = max((len(value[key]) for key in ("oneOf", "anyOf") if key in value), default=1)
        return max([own, *(_widest(inner) for inner in value.values())])
    if isinstance(value, list):
        return max((_widest(inner) for inner in value), default=1)
    return 1


VARIANTS = _widest(SPEC)
"""How many examples of a schema it takes to have every variant of its unions."""


def example_of(name: str, **overrides: Any) -> dict[str, Any]:
    """The contract's example of the schema `name` (`"Record"`), with some of its
    properties replaced, so a fixture has every property the contract has and no other."""
    built = copy.deepcopy(example({"$ref": pointer("components", "schemas", name)}))
    unknown = set(overrides) - set(built)
    assert not unknown, f"{name} has no {', '.join(sorted(unknown))} in the contract"
    return built | overrides
