"""Smoke test (Nohead spec §48.14): the core flow against a live API, with both
clients. Needs NOHEAD_API_URL and NOHEAD_API_KEY (a key with schema, records, assets
and webhooks read/write scopes). Exits non-zero on failure, after deleting what it
created. Run it against the built package:

    uv build
    NOHEAD_API_URL=http://localhost:3000 NOHEAD_API_KEY=sk_live_... \\
      uv run --isolated --no-project --with dist/nohead-*.whl python smoke/smoke.py
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
import uuid

from nohead import (
    AsyncNohead,
    Nohead,
    NotFoundError,
    PreconditionFailedError,
    ValidationError,
)

# What the test created and has not deleted yet, by resource: deleted at the end, also
# when it fails.
LEFT: dict[str, str] = {}


def expect(condition: object, message: str) -> None:
    if not condition:
        print(f"FAIL: {message}", file=sys.stderr)
        sys.exit(1)


def sync_flow() -> str:
    with Nohead() as nohead:
        me = nohead.me.get()
        expect(me.api_key and me.api_key.project_id, "the key belongs to a project")

        collection = nohead.collections.create(
            name="Python smoke",
            slug=f"sdk-python-{uuid.uuid4().hex[:8]}",
            fields=[{"name": "Title", "api_key": "title", "type": "text", "required": True}],
        )
        LEFT["collections"] = collection.id

        key = str(uuid.uuid4())
        first = nohead.records.create(collection.slug, data={"title": "One"}, idempotency_key=key)
        retried = nohead.records.create(collection.slug, data={"title": "One"}, idempotency_key=key)
        expect(retried.id == first.id, "an idempotent retry returns the same record")
        nohead.records.create(collection.slug, data={"title": "Two"})

        got = nohead.records.get(first.id)
        expect(got.data["title"] == "One", "get returns the record")

        updated = nohead.records.update(first.id, data={"title": "Uno"}, if_match=first)
        expect(
            updated.data["title"] == "Uno" and updated.revision == first.revision + 1,
            "update writes a revision",
        )
        try:
            nohead.records.update(first.id, data={"title": "Stale"}, if_match=first)
            expect(False, "a stale if_match is refused")
        except PreconditionFailedError as error:
            expect(error.current_revision == updated.revision, "a 412 reports the current revision")

        page = nohead.records.list(collection.slug, limit=1)
        expect(
            len(page.data) == 1 and page.has_next_page(), "the first page has one record and more"
        )
        following = page.get_next_page()
        expect(following.data[0].id != page.data[0].id, "the cursor returns the next page")
        titles = sorted(r.data["title"] for r in nohead.records.list(collection.slug, limit=1))
        expect(titles == ["Two", "Uno"], "iterating walks every page")

        # A comma inside a value is escaped, or "Two" would match too.
        chosen = nohead.records.list(
            collection.slug, filter={"title": {"in": ["Uno", "Two, or not"]}}
        )
        expect([r.data["title"] for r in chosen.data] == ["Uno"], "filters take operators")

        published = nohead.records.publish(first.id)
        expect(published.status == "published" and published.published_at, "publish publishes")
        unpublished = nohead.records.unpublish(first.id)
        expect(unpublished.status == "draft", "unpublish takes it back")

        try:
            nohead.records.create(collection.slug, data={})
            expect(False, "a record without its required field is refused")
        except ValidationError as error:
            expect(
                error.details and error.details[0].field == "title",
                "validation details name the field",
            )

        try:
            nohead.records.get("rec_01J9ZQ3F8X5W2K7M4N6P0R1S2T")
            expect(False, "a missing record is refused")
        except NotFoundError as error:
            expect((error.request_id or "").startswith("req_"), "API errors carry the request ID")

        asset = nohead.assets.upload(b"hello", filename="hello.txt")
        LEFT["assets"] = asset.id
        expect(asset.status == "ready" and asset.byte_size == 5, "assets upload to storage")
        expect(nohead.assets.delete(asset.id).deleted, "assets soft-delete")
        nohead.assets.purge(asset.id)
        del LEFT["assets"]

        webhook = nohead.webhooks.create(
            url="https://example.com/nohead-smoke", event_types=["record.published"]
        )
        LEFT["webhooks"] = webhook.id
        rotated = nohead.webhooks.rotate_secret(webhook.id)
        expect(
            webhook.secret.startswith("whsec_") and rotated.secret != webhook.secret,
            "rotating a webhook's secret replaces it",
        )
        expect(nohead.webhooks.delete(webhook.id).deleted, "webhooks delete")
        del LEFT["webhooks"]

        deleted = nohead.records.delete(first.id)
        expect(deleted.deleted, "delete soft-deletes")
        return collection.slug


async def async_flow(collection: str) -> None:
    async with AsyncNohead() as nohead:
        created = await nohead.records.create(collection, data={"title": "Async"})
        expect(
            (await nohead.records.get(created.id)).data["title"] == "Async",
            "the async client reads",
        )
        titles = [r.data["title"] async for r in nohead.records.list(collection, limit=1)]
        expect(sorted(titles) == ["Async", "Two"], "async iteration walks every page")
        await nohead.collections.delete(collection)
        del LEFT["collections"]


def clean_up() -> None:
    with Nohead() as nohead:
        for resource, id in LEFT.items():
            with contextlib.suppress(Exception):
                getattr(nohead, resource).delete(id)


try:
    slug = sync_flow()
    asyncio.run(async_flow(slug))
finally:
    clean_up()
print("python SDK smoke test passed")
