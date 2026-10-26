"""Smoke test (Nohead spec §48.14): the core flow against a live API, with both
clients. Needs NOHEAD_API_URL and NOHEAD_API_KEY (a key with schema, records, assets
and webhooks read/write scopes). Exits non-zero on failure, after deleting what it
created. Run it against the built package:

    uv build
    NOHEAD_API_URL=http://localhost:3000 NOHEAD_API_KEY=nohead_sk_... \\
      uv run --isolated --no-project --with dist/nohead-*.whl python smoke/smoke.py
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import sys
import tempfile
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import IO, Any

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


@contextlib.contextmanager
def pipe(data: bytes) -> Iterator[IO[bytes]]:
    """A stream that can't seek or tell its size, holding `data`."""
    read, write = os.pipe()
    with open(write, "wb") as writer:
        writer.write(data)  # small: it fits the pipe's buffer
    with open(read, "rb") as reader:
        yield reader


def sync_flow() -> str:
    with Nohead() as nohead:
        me = nohead.me.get()
        expect(me.api_key and me.api_key.project_id, "the key belongs to a project")

        collection = nohead.collections.create(
            name="Python smoke",
            slug=f"sdk-python-{uuid.uuid4().hex[:8]}",
            fields=[{"name": "Title", "key": "title", "type": "text", "required": True}],
        )
        LEFT["collections"] = collection.id

        key = str(uuid.uuid4())
        first = nohead.records.create(collection.slug, data={"title": "One"}, idempotency_key=key)
        retried = nohead.records.create(collection.slug, data={"title": "One"}, idempotency_key=key)
        expect(retried.id == first.id, "an idempotent retry returns the same record")
        for title in ["Two", "Three", "Four", "Five"]:
            nohead.records.create(collection.slug, data={"title": title})

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
        # Five records, two a page: iterating fetches three pages.
        walked = list(nohead.records.list(collection.slug, limit=2))
        expect(len({r.id for r in walked}) == len(walked), "iterating returns each record once")
        expect(
            sorted(r.data["title"] for r in walked) == ["Five", "Four", "Three", "Two", "Uno"],
            "iterating walks every page",
        )

        # A comma inside a value is escaped, or "Two" would match too.
        chosen = nohead.records.list(
            collection.slug, filter={"title": {"in": ["Uno", "Two, or not"]}}
        )
        expect([r.data["title"] for r in chosen.data] == ["Uno"], "filters take operators")

        published = nohead.records.publish(first.id)
        expect(published.published_at, "publish publishes")
        publication = nohead.records.publication(first.id)
        expect(publication.revision == published.revision, "the publication says what is live")
        draft = nohead.drafts.create(first.id, data={"title": "Uno, revised"})
        expect(
            nohead.records.get(first.id).data["title"] == "Uno",
            "a draft leaves the live record as it is",
        )
        merged = nohead.drafts.merge(draft.id, if_match=draft)
        expect(
            merged.data["title"] == "Uno, revised"
            and merged.published_at == published.published_at,
            "merging a draft changes the content, not the publication",
        )
        unpublished = nohead.records.unpublish(first.id)
        expect(unpublished.published_at is None, "unpublish takes it back")

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
        renamed = nohead.assets.update(asset.id, filename="greeting.txt")
        expect(renamed.filename == "greeting.txt", "assets rename")
        expect(nohead.assets.delete(asset.id).deleted_at, "assets soft-delete")
        nohead.assets.purge(asset.id)
        del LEFT["assets"]

        with tempfile.TemporaryDirectory() as directory:
            markdown = Path(directory, "notes.md")
            markdown.write_bytes(b"# Notes\n")
            table = Path(directory, "table.csv")
            table.write_bytes(b"a,b\n1,2\n")
            with table.open("rb") as opened, pipe(b"streamed bytes") as stream:
                uploads: list[tuple[str, Any, dict[str, Any], str, int]] = [
                    ("a path", markdown, {}, "text/markdown", 8),
                    ("a file object", opened, {}, "text/csv", 8),
                    (
                        "a stream that can't seek",
                        stream,
                        {"filename": "stream.txt", "byte_size": 14},
                        "text/plain",
                        14,
                    ),
                ]
                for kind, file, options, content_type, byte_size in uploads:
                    uploaded = nohead.assets.upload(file, **options)
                    LEFT["assets"] = uploaded.id
                    expect(
                        uploaded.status == "ready"
                        and uploaded.byte_size == byte_size
                        and uploaded.content_type == content_type,
                        f"{kind} uploads to storage",
                    )
                    nohead.assets.delete(uploaded.id)
                    nohead.assets.purge(uploaded.id)
                    del LEFT["assets"]

        webhook = nohead.webhooks.create(
            url="https://example.com/nohead-smoke", event_types=["record.published"]
        )
        LEFT["webhooks"] = webhook.id
        rotated = nohead.webhooks.rotate_secret(webhook.id)
        expect(
            webhook.secret.startswith("whsec_") and rotated.secret != webhook.secret,
            "rotating a webhook's secret adds one",
        )
        expect(
            len(nohead.webhooks.secrets.list(webhook.id).data) == 2,
            "the old secret signs alongside the new one",
        )
        expect(nohead.webhooks.delete(webhook.id).deleted_at, "webhooks delete")
        del LEFT["webhooks"]

        deleted = nohead.records.delete(first.id)
        expect(deleted.deleted_at, "delete soft-deletes")
        return collection.slug


async def async_flow(collection: str) -> None:
    async with AsyncNohead() as nohead:
        created = await nohead.records.create(collection, data={"title": "Async"})
        expect(
            (await nohead.records.get(created.id)).data["title"] == "Async",
            "the async client reads",
        )
        titles = [r.data["title"] async for r in nohead.records.list(collection, limit=2)]
        expect(
            sorted(titles) == ["Async", "Five", "Four", "Three", "Two"],
            "async iteration walks every page",
        )
        try:
            await nohead.records.get("rec_01J9ZQ3F8X5W2K7M4N6P0R1S2T")
            expect(False, "a missing record is refused")
        except NotFoundError as error:
            expect((error.request_id or "").startswith("req_"), "async errors carry the request ID")

        with pipe(b"streamed asynchronously") as stream:
            asset = await nohead.assets.upload(stream, filename="stream.txt", byte_size=23)
        LEFT["assets"] = asset.id
        expect(
            asset.status == "ready"
            and asset.byte_size == 23
            and asset.content_type == "text/plain",
            "the async client uploads a stream that can't seek",
        )
        await nohead.assets.delete(asset.id)
        await nohead.assets.purge(asset.id)
        del LEFT["assets"]
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
