"""Every API-key operation in the contract must be reachable from the SDK's public
methods, every request must match its operation (method, path, declared query parameters
and their values, and the JSON body), and every declared query parameter must be sent by
some call. A new operation or query parameter in openapi.json fails this test until a
method takes it (and a call in tests/calls.py or below passes it). Each call gets the
contract's example of its operation's response, and must return it, parsed without a
NoheadWarning. Both clients are checked."""

from __future__ import annotations

import inspect
import json
import re
from collections.abc import Callable
from datetime import datetime
from functools import cache
from typing import Any

import httpx
import pytest
from jsonschema import Draft202012Validator
from pydantic import BaseModel
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from nohead import AsyncNohead, AsyncPage, Nohead, Page
from nohead._generated.operations import OPERATIONS

from .calls import every_call, example_reply, mock_reply
from .conftest import Recorder, make_async, make_sync
from .spec import ROUTES, SPEC, Parameter, route_of

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


TIMESTAMP = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?(Z|[+-]\d\d:\d\d)")


def comparable(value: Any) -> Any:
    """A result or reply as JSON, with timestamps as datetimes: their formats differ."""
    if isinstance(value, Page | AsyncPage):
        return {"data": comparable(value.data), "meta": comparable(value.meta)}
    if isinstance(value, BaseModel):
        return comparable(value.model_dump(mode="json", by_alias=True))
    if isinstance(value, dict):
        return {key: comparable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [comparable(item) for item in value]
    if isinstance(value, str) and TIMESTAMP.fullmatch(value):
        return datetime.fromisoformat(value)
    return value


# Query parameters an API key has no use for: it always acts on its own project.
NOT_FOR_API_KEYS = {"feature_flags_list": {"organization_id", "project_id"}}


def every_parameter(nohead: Any) -> list[Callable[[], Any]]:
    """Calls that pass the query parameters the samples in tests/calls.py leave out."""
    return [
        lambda: nohead.records.list("posts", cursor="cur_x"),
        lambda: nohead.records.revisions.list("rec_01J9ZQ3F8X", limit=5, cursor="cur_x"),
        lambda: nohead.records.search("posts", "hello", limit=5, cursor="cur_x"),
        lambda: nohead.search("hello", limit=5, cursor="cur_x"),
        lambda: nohead.collections.list(limit=5, cursor="cur_x"),
        lambda: nohead.collections.schema_changes.list("posts", limit=5, cursor="cur_x"),
        lambda: nohead.fields.list("posts", limit=5, cursor="cur_x"),
        lambda: nohead.migrations.list("posts", limit=5, cursor="cur_x"),
        lambda: nohead.assets.list(content_type=["image/*"], limit=5, cursor="cur_x"),
        lambda: nohead.assets.image_url("ast_01J9ZQ3F8X", height=100, fit="cover", quality=80),
        lambda: nohead.webhooks.list(limit=5, cursor="cur_x"),
        lambda: nohead.webhooks.deliveries.list("wh_01J9ZQ3F8X", limit=5, cursor="cur_x"),
        lambda: nohead.audit_events.list(limit=5, cursor="cur_x"),
    ]


def check_requests(requests: list[httpx.Request], sent: dict[str, set[str]]) -> None:
    """Checks one call's requests against their operations, noting the parameters sent."""
    for request in requests:
        route = route_of(request.method, request.url.path)
        keys = {key.split("[", 1)[0] for key in request.url.params}
        declared = {p.name for p in route.query}
        assert keys <= declared, f"{route.id} sends undeclared query parameters {keys - declared}"
        values = query_values(request.url, route.query)
        for param in route.query:
            if param.name in values:
                problems = errors(param.schema_at, values[param.name])
                assert problems == [], f"{route.id} {param.name}"
        if request.content:
            assert route.body is not None, f"{route.id} takes no body"
            assert errors(route.body.schema_at, json.loads(request.content)) == [], (
                f"{route.id} body"
            )
        else:
            assert not route.body_required, f"{route.id} needs a body"
        sent.setdefault(route.id, set()).update(keys)


def check_result(requests: list[httpx.Request], result: Any) -> None:
    """The method returns the response its last request got."""
    last = requests[-1]
    reply = example_reply(route_of(last.method, last.url.path), last)
    assert comparable(result) == comparable(reply)


def check_coverage(sent: dict[str, set[str]]) -> None:
    assert sorted(set(OPERATIONS) - set(sent)) == [], "operations without an SDK method"
    unsent = {
        route.id: sorted(
            {p.name for p in route.query} - sent[route.id] - NOT_FOR_API_KEYS.get(route.id, set())
        )
        for route in ROUTES
    }
    assert {op: p for op, p in unsent.items() if p} == {}, "query parameters no call sends"


def api_requests(recorder: Recorder, start: int) -> list[httpx.Request]:
    return [r for r in recorder.calls[start:] if r.url.host == "api.test"]


@pytest.mark.filterwarnings("error::nohead.NoheadWarning")
def test_the_sync_client_covers_the_contract() -> None:
    nohead, recorder = make_sync([mock_reply])
    sent: dict[str, set[str]] = {}
    for call in every_call(nohead) + every_parameter(nohead):
        start = len(recorder.calls)
        result = call()
        check_requests(api_requests(recorder, start), sent)
        check_result(api_requests(recorder, start), result)
    check_coverage(sent)


@pytest.mark.filterwarnings("error::nohead.NoheadWarning")
async def test_the_async_client_covers_the_contract() -> None:
    nohead, recorder = make_async([mock_reply])
    sent: dict[str, set[str]] = {}
    for call in every_call(nohead) + every_parameter(nohead):
        start = len(recorder.calls)
        result = call()
        if inspect.isawaitable(result):
            result = await result
        check_requests(api_requests(recorder, start), sent)
        check_result(api_requests(recorder, start), result)
    check_coverage(sent)


def test_every_success_response_has_a_valid_example() -> None:
    for route in ROUTES:
        request = httpx.Request(route.method, "https://api.test/")
        assert errors(route.response.schema_at, example_reply(route, request)) == [], route.id


def test_both_clients_have_the_same_methods() -> None:
    def methods(obj: object, prefix: str = "") -> set[str]:
        found: set[str] = set()
        for name in dir(obj):
            if name.startswith("_") or name in {"with_options", "close"}:
                continue
            value = getattr(obj, name)
            if callable(value):
                found.add(prefix + name)
            elif hasattr(value, "_client"):
                found |= methods(value, f"{prefix}{name}.")
        return found

    sync = methods(Nohead(api_key="sk_live_x"))
    assert sync == methods(AsyncNohead(api_key="sk_live_x"))
    assert "records.revisions.revert" in sync
