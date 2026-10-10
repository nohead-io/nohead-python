"""One call per API-key operation, with arguments as the docs should show them. The
contract test runs every call against the contract, and scripts/samples.py turns each
into the API reference's code sample for the operation it calls (samples.json)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx

from .conftest import json_response
from .spec import Route, example, route_of


def mock_reply(request: httpx.Request) -> httpx.Response:
    """The reply to any of the calls in every_call: the contract's example of the
    operation's success response (tests/spec.py), with an upload URL on storage."""
    if request.url.host == "storage.test":
        return httpx.Response(200)
    route = route_of(request.method, request.url.path)
    return json_response(route.status, example_reply(route, request))


def example_reply(route: Route, request: httpx.Request) -> Any:
    """The body of mock_reply for a request of an operation."""
    schema = route.response.schema
    if request.url.params.get("dry_run") == "true" and "oneOf" in schema:
        schema = schema["oneOf"][-1]  # the preview (records.revisions.revert)
    body = example(schema)
    if route.id == "assets_upload":
        body["upload"]["url"] = "https://storage.test/u"
    return body


def every_call(nohead: Any) -> list[Callable[[], Any]]:
    """One call per API-key operation, with arguments as the docs should show them."""
    return [
        lambda: nohead.records.list(
            "posts", filter={"status": "published"}, sort="-created_at", expand=["author"], limit=5
        ),
        lambda: nohead.records.get("rec_01J9ZQ3F8X", expand=["author"], include_deleted=True),
        lambda: nohead.records.create("posts", data={"title": "Hi"}),
        lambda: nohead.records.update("rec_01J9ZQ3F8X", data={"title": "Hey"}, if_match=1),
        lambda: nohead.records.delete("rec_01J9ZQ3F8X"),
        lambda: nohead.records.restore("rec_01J9ZQ3F8X"),
        lambda: nohead.records.publish("rec_01J9ZQ3F8X"),
        lambda: nohead.records.unpublish("rec_01J9ZQ3F8X"),
        lambda: nohead.records.schedule("rec_01J9ZQ3F8X", publish_at="2027-01-01T00:00:00Z"),
        lambda: nohead.records.unschedule("rec_01J9ZQ3F8X"),
        lambda: nohead.records.count("posts", filter={"status": "draft"}),
        lambda: nohead.records.bulk("posts", action="publish", record_ids=["rec_01J9ZQ3F8X"]),
        lambda: nohead.records.diff("rec_01J9ZQ3F8X", 1, 2),
        lambda: nohead.records.search(
            "posts",
            "hello",
            filter={"status": "published"},
            sort="-published_at",
            expand=["author"],
        ),
        lambda: nohead.records.revisions.list("rec_01J9ZQ3F8X", filter={"operation": "update"}),
        lambda: nohead.records.revisions.get("rec_01J9ZQ3F8X", 1),
        lambda: nohead.records.revisions.revert("rec_01J9ZQ3F8X", 1, dry_run=True),
        lambda: nohead.search("hello", collections=["posts"], status="published"),
        lambda: nohead.collections.list(deleted=True),
        lambda: nohead.collections.get("posts"),
        lambda: nohead.collections.create(name="Posts", slug="posts"),
        lambda: nohead.collections.update("posts", name="Articles"),
        lambda: nohead.collections.delete("posts"),
        lambda: nohead.collections.restore("posts"),
        lambda: nohead.collections.schema("posts", version=2),
        lambda: nohead.collections.schema_changes.list("posts"),
        lambda: nohead.collections.schema_changes.get("posts", "sch_01J9ZQ3F8X"),
        lambda: nohead.collections.search_index.get("posts"),
        lambda: nohead.collections.search_index.rebuild("posts"),
        lambda: nohead.fields.list("posts", deleted=True),
        lambda: nohead.fields.create("posts", name="Title", api_key="title", type="text"),
        lambda: nohead.fields.update("fld_01J9ZQ3F8X", name="Heading"),
        lambda: nohead.fields.delete("fld_01J9ZQ3F8X"),
        lambda: nohead.fields.restore("fld_01J9ZQ3F8X"),
        lambda: nohead.fields.reorder("posts", ["fld_01J9ZQ3F8X"]),
        lambda: nohead.fields.remove_alias("fld_01J9ZQ3F8X", "old_title"),
        lambda: nohead.fields.migrate("fld_01J9ZQ3F8X", type="long_text", dry_run=True),
        lambda: nohead.migrations.list("posts"),
        lambda: nohead.migrations.get("mig_01J9ZQ3F8X"),
        lambda: nohead.migrations.cancel("mig_01J9ZQ3F8X"),
        lambda: nohead.assets.upload(b"Hello", filename="hello.txt"),
        lambda: nohead.assets.create_upload(
            filename="hello.txt", content_type="text/plain", byte_size=5
        ),
        lambda: nohead.assets.complete("ast_01J9ZQ3F8X"),
        lambda: nohead.assets.list(deleted=True),
        lambda: nohead.assets.get("ast_01J9ZQ3F8X"),
        lambda: nohead.assets.delete("ast_01J9ZQ3F8X"),
        lambda: nohead.assets.restore("ast_01J9ZQ3F8X"),
        lambda: nohead.assets.purge("ast_01J9ZQ3F8X"),
        lambda: nohead.assets.usage("ast_01J9ZQ3F8X"),
        lambda: nohead.assets.image_url("ast_01J9ZQ3F8X", width=100, format="webp"),
        lambda: nohead.assets.download_url("ast_01J9ZQ3F8X"),
        lambda: nohead.webhooks.list(),
        lambda: nohead.webhooks.get("wh_01J9ZQ3F8X"),
        lambda: nohead.webhooks.create(url="https://example.com/hook", event_types=["*"]),
        lambda: nohead.webhooks.update("wh_01J9ZQ3F8X", enabled=False),
        lambda: nohead.webhooks.delete("wh_01J9ZQ3F8X"),
        lambda: nohead.webhooks.rotate_secret("wh_01J9ZQ3F8X"),
        lambda: nohead.webhooks.test("wh_01J9ZQ3F8X"),
        lambda: nohead.webhooks.deliveries.list("wh_01J9ZQ3F8X", status="failed"),
        lambda: nohead.webhooks.deliveries.get("whd_01J9ZQ3F8X"),
        lambda: nohead.webhooks.deliveries.retry("whd_01J9ZQ3F8X"),
        lambda: nohead.audit_events.list(filter={"action": "record.*"}, sort="-id"),
        lambda: nohead.feature_flags.list(),
        lambda: nohead.me.get(),
        lambda: nohead.health.check(),
    ]
