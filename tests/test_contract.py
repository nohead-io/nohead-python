"""Every API-key operation in the contract must be reachable from the SDK's public
methods, and every request must match its operation: method, path and declared query
parameters. A new operation in openapi.json fails this test until a method (and a
call below) covers it. Both clients are checked."""

from __future__ import annotations

import inspect
import json
import re
from pathlib import Path

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


def check(requests: list[httpx.Request]) -> None:
    api = [r for r in requests if r.url.host == "api.test"]
    for request in api:
        op, params = operation_of(request)
        sent = {key.split("[", 1)[0] for key in request.url.params}
        assert sent <= set(params), f"{op} sends undeclared query parameters {sent - set(params)}"
    covered = {operation_of(r)[0] for r in api}
    assert sorted(set(OPERATIONS) - covered) == [], "operations without an SDK method"


@pytest.mark.filterwarnings("ignore::nohead.NoheadWarning")
def test_the_sync_client_covers_the_contract() -> None:
    nohead, recorder = make_sync([mock_reply])
    for call in every_call(nohead):
        result = call()
        if hasattr(result, "data") and hasattr(result, "has_next_page"):
            list(result.data)
    check(recorder.calls)


@pytest.mark.filterwarnings("ignore::nohead.NoheadWarning")
async def test_the_async_client_covers_the_contract() -> None:
    nohead, recorder = make_async([mock_reply])
    for call in every_call(nohead):
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
