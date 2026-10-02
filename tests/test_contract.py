"""Every API-key operation in the contract must be reachable from the SDK's public
methods, and every request must match its operation: method, path and declared query
parameters. A new operation in openapi.json fails this test until a method (and a
call below) covers it. Both clients are checked."""

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

from .conftest import json_response, make_async, make_sync, page, record

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


UPLOAD = {
    "object": "asset_upload",
    "asset": {"id": "ast_1", "filename": "a.txt"},  # incomplete on purpose: built unvalidated
    "upload": {
        "method": "PUT",
        "url": "https://storage.test/u",
        "headers": {},
        "expires_at": "2026-10-02T13:00:00.000Z",
    },
}
LISTS = re.compile(
    r"/(records|collections|fields|assets|webhooks|deliveries|revisions|schema-changes|migrations|audit-events|search)$"
)


def reply(request: httpx.Request) -> httpx.Response:
    if request.url.host == "storage.test":
        return httpx.Response(200)
    if request.url.path.endswith("/assets/uploads"):
        return json_response(201, UPLOAD)
    if request.method == "GET" and LISTS.search(request.url.path):
        return page([record("rec_1")], None)
    return json_response(200, record("rec_1"))


def every_method(n: Any) -> list[Callable[[], Any]]:
    return [
        lambda: n.records.list(
            "posts", filter={"status": "published"}, sort="-created_at", expand=["author"], limit=5
        ),
        lambda: n.records.get("rec_1", expand=["author"], include_deleted=True),
        lambda: n.records.create("posts", data={"title": "Hi"}),
        lambda: n.records.update("rec_1", data={"title": "Hey"}, if_match=1),
        lambda: n.records.delete("rec_1"),
        lambda: n.records.restore("rec_1"),
        lambda: n.records.publish("rec_1"),
        lambda: n.records.unpublish("rec_1"),
        lambda: n.records.schedule("rec_1", publish_at="2027-01-01T00:00:00Z"),
        lambda: n.records.unschedule("rec_1"),
        lambda: n.records.count("posts", filter={"status": "draft"}),
        lambda: n.records.bulk("posts", action="publish", record_ids=["rec_1"]),
        lambda: n.records.diff("rec_1", 1, 2),
        lambda: n.records.search(
            "posts",
            "hello",
            filter={"status": "published"},
            sort="-published_at",
            expand=["author"],
        ),
        lambda: n.records.revisions.list("rec_1", filter={"operation": "update"}),
        lambda: n.records.revisions.get("rec_1", 1),
        lambda: n.records.revisions.revert("rec_1", 1, dry_run=True),
        lambda: n.search("hello", collections=["posts"], status="published"),
        lambda: n.collections.list(deleted=True),
        lambda: n.collections.get("posts"),
        lambda: n.collections.create(name="Posts", slug="posts"),
        lambda: n.collections.update("posts", name="Articles"),
        lambda: n.collections.delete("posts"),
        lambda: n.collections.restore("posts"),
        lambda: n.collections.schema("posts", version=2),
        lambda: n.collections.schema_changes.list("posts"),
        lambda: n.collections.schema_changes.get("posts", "sch_1"),
        lambda: n.collections.search_index.get("posts"),
        lambda: n.collections.search_index.rebuild("posts"),
        lambda: n.fields.list("posts", deleted=True),
        lambda: n.fields.create("posts", name="Title", api_key="title", type="text"),
        lambda: n.fields.update("fld_1", name="Heading"),
        lambda: n.fields.delete("fld_1"),
        lambda: n.fields.restore("fld_1"),
        lambda: n.fields.reorder("posts", ["fld_1"]),
        lambda: n.fields.remove_alias("fld_1", "old_title"),
        lambda: n.fields.migrate("fld_1", type="long_text", dry_run=True),
        lambda: n.migrations.list("posts"),
        lambda: n.migrations.get("mig_1"),
        lambda: n.migrations.cancel("mig_1"),
        lambda: n.assets.upload(b"x", filename="a.txt"),
        lambda: n.assets.list(deleted=True),
        lambda: n.assets.get("ast_1"),
        lambda: n.assets.delete("ast_1"),
        lambda: n.assets.restore("ast_1"),
        lambda: n.assets.image_url("ast_1", width=100, format="webp"),
        lambda: n.assets.download_url("ast_1"),
        lambda: n.webhooks.list(),
        lambda: n.webhooks.get("wh_1"),
        lambda: n.webhooks.create(url="https://example.com/hook", event_types=["*"]),
        lambda: n.webhooks.update("wh_1", enabled=False),
        lambda: n.webhooks.delete("wh_1"),
        lambda: n.webhooks.rotate_secret("wh_1"),
        lambda: n.webhooks.test("wh_1"),
        lambda: n.webhooks.deliveries.list("wh_1", status="failed"),
        lambda: n.webhooks.deliveries.get("whd_1"),
        lambda: n.webhooks.deliveries.retry("whd_1"),
        lambda: n.audit_events.list(filter={"action": "record.*"}, sort="-id"),
        lambda: n.feature_flags.list(),
        lambda: n.me.get(),
        lambda: n.health.check(),
    ]


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
    nohead, recorder = make_sync([reply])
    for call in every_method(nohead):
        result = call()
        if hasattr(result, "data") and hasattr(result, "has_next_page"):
            list(result.data)
    check(recorder.calls)


@pytest.mark.filterwarnings("ignore::nohead.NoheadWarning")
async def test_the_async_client_covers_the_contract() -> None:
    nohead, recorder = make_async([reply])
    for call in every_method(nohead):
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
