from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any, Literal, overload

from typing_extensions import Unpack

from ..._pagination import AsyncPaginator
from ...models import (
    BulkRecordsResult,
    Record,
    RecordCount,
    RecordDiff,
    RecordRevision,
    RecordRevisionDetail,
    RevertPreview,
    SearchResultsMeta,
)
from ...params import BulkRecordsRequest, RecordWrite
from ...types import IfMatch, RecordFilter, RecordSort
from .._client import AsyncAPIClient
from ._resource import AsyncResource


class AsyncRecords(AsyncResource):
    """Records: the content of a collection. `collection` is a collection ID or
    slug; `record` a record ID (`rec_...`)."""

    def __init__(self, client: AsyncAPIClient) -> None:
        super().__init__(client)
        self.revisions = AsyncRevisions(client)

    def list(
        self,
        collection: str,
        *,
        filter: RecordFilter | None = None,
        sort: RecordSort | None = None,
        expand: Sequence[str] | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> AsyncPaginator[Record]:
        """A collection's records, newest first by default.

        `filter` holds equality filters (`{"status": "published"}`), `expand` relation
        or asset fields to embed under `expanded` (at most 5).
        """
        return self._client.paginate(
            "records_list",
            item=Record,
            path={"collection_id": collection},
            query={
                "filter": filter,
                "sort": sort,
                "expand": expand,
                "limit": limit,
                "cursor": cursor,
            },
        )

    async def get(
        self,
        record: str,
        *,
        expand: Sequence[str] | None = None,
        include_deleted: bool | None = None,
    ) -> Record:
        return await self._client.request(
            "records_get",
            cast=Record,
            path={"record_id": record},
            query={"expand": expand, "include_deleted": include_deleted},
        )

    async def create(
        self,
        collection: str,
        *,
        idempotency_key: str | None = None,
        change_note: str | None = None,
        **params: Unpack[RecordWrite],
    ) -> Record:
        """Creates a draft: `create("posts", data={"title": "Hello"})`."""
        return await self._client.request(
            "records_create",
            cast=Record,
            path={"collection_id": collection},
            body=params,
            idempotency_key=idempotency_key,
            change_note=change_note,
        )

    async def update(
        self,
        record: str,
        *,
        if_match: IfMatch | None = None,
        idempotency_key: str | None = None,
        change_note: str | None = None,
        **params: Unpack[RecordWrite],
    ) -> Record:
        """Sets the given fields (None clears one); others keep their values."""
        return await self._client.request(
            "records_update",
            cast=Record,
            path={"record_id": record},
            body=params,
            if_match=if_match,
            idempotency_key=idempotency_key,
            change_note=change_note,
        )

    async def delete(
        self,
        record: str,
        *,
        if_match: IfMatch | None = None,
        idempotency_key: str | None = None,
        change_note: str | None = None,
    ) -> Record:
        """Soft-deletes the record: `restore` brings it back within 30 days."""
        return await self._client.request(
            "records_delete",
            cast=Record,
            path={"record_id": record},
            if_match=if_match,
            idempotency_key=idempotency_key,
            change_note=change_note,
        )

    async def restore(
        self,
        record: str,
        *,
        idempotency_key: str | None = None,
        change_note: str | None = None,
    ) -> Record:
        return await self._client.request(
            "records_restore",
            cast=Record,
            path={"record_id": record},
            idempotency_key=idempotency_key,
            change_note=change_note,
        )

    async def publish(
        self,
        record: str,
        *,
        if_match: IfMatch | None = None,
        idempotency_key: str | None = None,
        change_note: str | None = None,
    ) -> Record:
        return await self._client.request(
            "records_publish",
            cast=Record,
            path={"record_id": record},
            if_match=if_match,
            idempotency_key=idempotency_key,
            change_note=change_note,
        )

    async def unpublish(
        self,
        record: str,
        *,
        if_match: IfMatch | None = None,
        idempotency_key: str | None = None,
        change_note: str | None = None,
    ) -> Record:
        return await self._client.request(
            "records_unpublish",
            cast=Record,
            path={"record_id": record},
            if_match=if_match,
            idempotency_key=idempotency_key,
            change_note=change_note,
        )

    async def schedule(
        self,
        record: str,
        *,
        publish_at: datetime | str | None = None,
        unpublish_at: datetime | str | None = None,
        clear: Sequence[Literal["publish_at", "unpublish_at"]] = (),
        idempotency_key: str | None = None,
    ) -> Record:
        """Publishes and/or unpublishes the record later. Times left out keep their
        value; name them in `clear` to remove them."""
        body: dict[str, Any] = {name: None for name in clear}
        if publish_at is not None:
            body["publish_at"] = publish_at
        if unpublish_at is not None:
            body["unpublish_at"] = unpublish_at
        return await self._client.request(
            "records_schedule",
            cast=Record,
            path={"record_id": record},
            body=body,
            idempotency_key=idempotency_key,
        )

    async def unschedule(self, record: str, *, idempotency_key: str | None = None) -> Record:
        """Clears both scheduled times."""
        return await self._client.request(
            "records_unschedule",
            cast=Record,
            path={"record_id": record},
            idempotency_key=idempotency_key,
        )

    async def count(self, collection: str, *, filter: RecordFilter | None = None) -> RecordCount:
        return await self._client.request(
            "records_count",
            cast=RecordCount,
            path={"collection_id": collection},
            query={"filter": filter},
        )

    async def bulk(
        self,
        collection: str,
        *,
        idempotency_key: str | None = None,
        change_note: str | None = None,
        **params: Unpack[BulkRecordsRequest],
    ) -> BulkRecordsResult:
        """Publishes, unpublishes, deletes, restores or updates up to 100 records.
        Each record succeeds or fails on its own; see `results`."""
        return await self._client.request(
            "records_bulk",
            cast=BulkRecordsResult,
            path={"collection_id": collection},
            body=params,
            idempotency_key=idempotency_key,
            change_note=change_note,
        )

    async def diff(self, record: str, from_revision: int, to_revision: int) -> RecordDiff:
        """The changes between two revisions."""
        return await self._client.request(
            "records_diff",
            cast=RecordDiff,
            path={"record_id": record},
            query={"from": from_revision, "to": to_revision},
        )

    def search(
        self,
        collection: str,
        query: str,
        *,
        filter: RecordFilter | None = None,
        sort: str | None = None,
        expand: Sequence[str] | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> AsyncPaginator[Record, SearchResultsMeta]:
        """Full-text search in one collection (`search_enabled` collections), most
        relevant first, through the first 1,000 hits."""
        return self._client.paginate(
            "collections_search",
            item=Record,
            meta=SearchResultsMeta,
            path={"collection_id": collection},
            query={
                "q": query,
                "filter": filter,
                "sort": sort,
                "expand": expand,
                "limit": limit,
                "cursor": cursor,
            },
        )


class AsyncRevisions(AsyncResource):
    """A record's version history. `revision` is a revision number."""

    def list(
        self,
        record: str,
        *,
        filter: RecordFilter | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> AsyncPaginator[RecordRevision]:
        """Newest first. `filter` takes `operation`, `actor_id`, `since` and `until`."""
        return self._client.paginate(
            "record_revisions_list",
            item=RecordRevision,
            path={"record_id": record},
            query={"filter": filter, "limit": limit, "cursor": cursor},
        )

    async def get(self, record: str, revision: int) -> RecordRevisionDetail:
        return await self._client.request(
            "record_revisions_get",
            cast=RecordRevisionDetail,
            path={"record_id": record, "revision": revision},
        )

    @overload
    async def revert(
        self,
        record: str,
        revision: int,
        *,
        dry_run: Literal[True],
        if_match: IfMatch | None = None,
        idempotency_key: str | None = None,
    ) -> RevertPreview: ...
    @overload
    async def revert(
        self,
        record: str,
        revision: int,
        *,
        dry_run: Literal[False] = False,
        if_match: IfMatch | None = None,
        idempotency_key: str | None = None,
    ) -> Record: ...
    async def revert(
        self,
        record: str,
        revision: int,
        *,
        dry_run: bool = False,
        if_match: IfMatch | None = None,
        idempotency_key: str | None = None,
    ) -> Record | RevertPreview:
        """Restores the record's data as of `revision`, as a new revision. With
        `dry_run=True`, previews it."""
        return await self._client.request(
            "record_revisions_revert",
            cast=RevertPreview if dry_run else Record,
            path={"record_id": record, "revision": revision},
            query={"dry_run": dry_run or None},
            if_match=if_match,
            idempotency_key=idempotency_key,
        )
