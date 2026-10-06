"""Every API-key operation in the contract must be reachable from the SDK's public
methods, every request must match its operation (method, path and declared query
parameters), and every declared query parameter must be sent by some call. A new
operation or query parameter in openapi.json fails this test until a method takes it
(and a call in tests/calls.py or below passes it). Both clients are checked."""

from __future__ import annotations

import inspect
import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from nohead import AsyncNohead, Nohead
from nohead._generated.operations import OPERATIONS

from .calls import every_call, mock_reply
from .conftest import make_async, make_sync

SPEC = json.loads(Path("openapi.json").read_text())


def _params(path: str, method: str) -> list[str]:
    item = SPEC["paths"][path]
    found = []
    for parameter in item.get("parameters", []) + item[method.lower()].get("parameters", []):
        if "$ref" in parameter:
            parameter = SPEC["components"]["parameters"][parameter["$ref"].rsplit("/", 1)[1]]
        if parameter["in"] == "query":
            found.append(parameter["name"])
    return found


ROUTES = [
    (op, method, re.compile("^" + re.sub(r"\{\w+\}", "[^/]+", path) + "$"), _params(path, method))
    for op, (method, path) in OPERATIONS.items()
]


def operation_of(request: httpx.Request) -> tuple[str, list[str]]:
    for op, method, pattern, params in ROUTES:
        if method == request.method and pattern.match(request.url.path):
            return op, params
    raise AssertionError(f"No operation for {request.method} {request.url.path}")


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


def check(requests: list[httpx.Request]) -> None:
    api = [r for r in requests if r.url.host == "api.test"]
    sent: dict[str, set[str]] = {}
    for request in api:
        op, params = operation_of(request)
        keys = {key.split("[", 1)[0] for key in request.url.params}
        assert keys <= set(params), f"{op} sends undeclared query parameters {keys - set(params)}"
        sent.setdefault(op, set()).update(keys)
    assert sorted(set(OPERATIONS) - set(sent)) == [], "operations without an SDK method"
    unsent = {
        op: sorted(set(params) - sent[op] - NOT_FOR_API_KEYS.get(op, set()))
        for op, _, _, params in ROUTES
    }
    assert {op: p for op, p in unsent.items() if p} == {}, "query parameters no call sends"


@pytest.mark.filterwarnings("ignore::nohead.NoheadWarning")
def test_the_sync_client_covers_the_contract() -> None:
    nohead, recorder = make_sync([mock_reply])
    for call in every_call(nohead) + every_parameter(nohead):
        call()
    check(recorder.calls)


@pytest.mark.filterwarnings("ignore::nohead.NoheadWarning")
async def test_the_async_client_covers_the_contract() -> None:
    nohead, recorder = make_async([mock_reply])
    for call in every_call(nohead) + every_parameter(nohead):
        result = call()
        if inspect.isawaitable(result):
            await result
    check(recorder.calls)


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
