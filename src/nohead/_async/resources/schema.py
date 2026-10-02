from __future__ import annotations

from collections.abc import Sequence
from typing import Literal, overload

from typing_extensions import Unpack

from ..._pagination import AsyncPaginator
from ...models import (
    Collection,
    Field,
    FieldMigration,
    FieldMigrationPreview,
    Schema,
    SchemaChange,
    SchemaChangeDetail,
    SearchIndex,
)
from ...params import (
    CollectionCreate,
    CollectionUpdate,
    FieldCreate,
    FieldMigrationRequest,
    FieldUpdate,
)
from .._client import AsyncAPIClient
from ._resource import AsyncResource


class AsyncCollections(AsyncResource):
    """Collections of the key's project. `collection` is an ID or slug."""

    def __init__(self, client: AsyncAPIClient) -> None:
        super().__init__(client)
        self.schema_changes = AsyncSchemaChanges(client)
        self.search_index = AsyncSearchIndexes(client)

    def list(
        self, *, deleted: bool | None = None, limit: int | None = None, cursor: str | None = None
    ) -> AsyncPaginator[Collection]:
        """`deleted=True` lists deleted collections instead (restorable for 30 days)."""
        return self._client.paginate(
            "collections_list",
            item=Collection,
            query={"deleted": deleted, "limit": limit, "cursor": cursor},
        )

    async def get(self, collection: str) -> Collection:
        return await self._client.request(
            "collections_get", cast=Collection, path={"collection_id": collection}
        )

    async def create(
        self,
        *,
        idempotency_key: str | None = None,
        change_note: str | None = None,
        **params: Unpack[CollectionCreate],
    ) -> Collection:
        """Creates a collection, optionally with its fields."""
        return await self._client.request(
            "collections_create",
            cast=Collection,
            body=params,
            idempotency_key=idempotency_key,
            change_note=change_note,
        )

    async def update(
        self,
        collection: str,
        *,
        idempotency_key: str | None = None,
        change_note: str | None = None,
        **params: Unpack[CollectionUpdate],
    ) -> Collection:
        return await self._client.request(
            "collections_update",
            cast=Collection,
            path={"collection_id": collection},
            body=params,
            idempotency_key=idempotency_key,
            change_note=change_note,
        )

    async def delete(
        self, collection: str, *, idempotency_key: str | None = None, change_note: str | None = None
    ) -> Collection:
        """Soft-deletes the collection and its records for 30 days."""
        return await self._client.request(
            "collections_delete",
            cast=Collection,
            path={"collection_id": collection},
            idempotency_key=idempotency_key,
            change_note=change_note,
        )

    async def restore(
        self, collection: str, *, idempotency_key: str | None = None, change_note: str | None = None
    ) -> Collection:
        return await self._client.request(
            "collections_restore",
            cast=Collection,
            path={"collection_id": collection},
            idempotency_key=idempotency_key,
            change_note=change_note,
        )

    async def schema(self, collection: str, *, version: int | None = None) -> Schema:
        """The collection's schema, now or at a past `version`."""
        return await self._client.request(
            "collections_get_schema",
            cast=Schema,
            path={"collection_id": collection},
            query={"version": version},
        )


class AsyncSchemaChanges(AsyncResource):
    """A collection's schema history, newest first."""

    def list(
        self, collection: str, *, limit: int | None = None, cursor: str | None = None
    ) -> AsyncPaginator[SchemaChange]:
        return self._client.paginate(
            "schema_changes_list",
            item=SchemaChange,
            path={"collection_id": collection},
            query={"limit": limit, "cursor": cursor},
        )

    async def get(self, collection: str, schema_change: str) -> SchemaChangeDetail:
        return await self._client.request(
            "schema_changes_get",
            cast=SchemaChangeDetail,
            path={"collection_id": collection, "schema_change_id": schema_change},
        )


class AsyncSearchIndexes(AsyncResource):
    """A collection's search index."""

    async def get(self, collection: str) -> SearchIndex:
        return await self._client.request(
            "search_index_get", cast=SearchIndex, path={"collection_id": collection}
        )

    async def rebuild(self, collection: str, *, idempotency_key: str | None = None) -> SearchIndex:
        """Rebuilds the index from the records; searches keep working meanwhile."""
        return await self._client.request(
            "search_index_rebuild",
            cast=SearchIndex,
            path={"collection_id": collection},
            idempotency_key=idempotency_key,
        )


class AsyncFields(AsyncResource):
    """Fields of a collection. `field` is a field ID (`fld_...`)."""

    def list(
        self,
        collection: str,
        *,
        deleted: bool | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> AsyncPaginator[Field]:
        return self._client.paginate(
            "fields_list",
            item=Field,
            path={"collection_id": collection},
            query={"deleted": deleted, "limit": limit, "cursor": cursor},
        )

    async def create(
        self,
        collection: str,
        *,
        idempotency_key: str | None = None,
        change_note: str | None = None,
        **params: Unpack[FieldCreate],
    ) -> Field:
        return await self._client.request(
            "fields_create",
            cast=Field,
            path={"collection_id": collection},
            body=params,
            idempotency_key=idempotency_key,
            change_note=change_note,
        )

    async def update(
        self,
        field: str,
        *,
        idempotency_key: str | None = None,
        change_note: str | None = None,
        **params: Unpack[FieldUpdate],
    ) -> Field:
        """Renames, describes or loosens a field. Changes that rewrite record values
        (type, `multiple`, tighter rules) are `migrate`."""
        return await self._client.request(
            "fields_update",
            cast=Field,
            path={"field_id": field},
            body=params,
            idempotency_key=idempotency_key,
            change_note=change_note,
        )

    async def delete(
        self, field: str, *, idempotency_key: str | None = None, change_note: str | None = None
    ) -> Field:
        """Soft-deletes the field: its values return with `restore` for 30 days."""
        return await self._client.request(
            "fields_delete",
            cast=Field,
            path={"field_id": field},
            idempotency_key=idempotency_key,
            change_note=change_note,
        )

    async def restore(
        self, field: str, *, idempotency_key: str | None = None, change_note: str | None = None
    ) -> Field:
        return await self._client.request(
            "fields_restore",
            cast=Field,
            path={"field_id": field},
            idempotency_key=idempotency_key,
            change_note=change_note,
        )

    async def reorder(
        self,
        collection: str,
        field_ids: Sequence[str],
        *,
        idempotency_key: str | None = None,
        change_note: str | None = None,
    ) -> Collection:
        """Puts the collection's fields in this order."""
        return await self._client.request(
            "fields_reorder",
            cast=Collection,
            path={"collection_id": collection},
            body={"field_ids": list(field_ids)},
            idempotency_key=idempotency_key,
            change_note=change_note,
        )

    async def remove_alias(
        self, field: str, alias: str, *, idempotency_key: str | None = None
    ) -> Field:
        """Stops accepting a renamed field's old API key before its 6 months end."""
        return await self._client.request(
            "fields_remove_alias",
            cast=Field,
            path={"field_id": field, "alias": alias},
            idempotency_key=idempotency_key,
        )

    @overload
    async def migrate(
        self,
        field: str,
        *,
        dry_run: Literal[True],
        idempotency_key: str | None = None,
        change_note: str | None = None,
        **params: Unpack[FieldMigrationRequest],
    ) -> FieldMigrationPreview: ...
    @overload
    async def migrate(
        self,
        field: str,
        *,
        dry_run: Literal[False] = False,
        idempotency_key: str | None = None,
        change_note: str | None = None,
        **params: Unpack[FieldMigrationRequest],
    ) -> FieldMigration: ...
    async def migrate(
        self,
        field: str,
        *,
        dry_run: bool = False,
        idempotency_key: str | None = None,
        change_note: str | None = None,
        **params: Unpack[FieldMigrationRequest],
    ) -> FieldMigration | FieldMigrationPreview:
        """Starts a field migration (type, `multiple`, tighter configuration or a
        backfill) that rewrites every record. With `dry_run=True`, previews it."""
        return await self._client.request(
            "fields_migrate",
            cast=FieldMigrationPreview if dry_run else FieldMigration,
            path={"field_id": field},
            query={"dry_run": dry_run or None},
            body=params,
            idempotency_key=idempotency_key,
            change_note=change_note,
        )


class AsyncMigrations(AsyncResource):
    """Field migrations. While one runs, its collection is read-only."""

    def list(
        self, collection: str, *, limit: int | None = None, cursor: str | None = None
    ) -> AsyncPaginator[FieldMigration]:
        return self._client.paginate(
            "migrations_list",
            item=FieldMigration,
            path={"collection_id": collection},
            query={"limit": limit, "cursor": cursor},
        )

    async def get(self, migration: str) -> FieldMigration:
        return await self._client.request(
            "migrations_get", cast=FieldMigration, path={"migration_id": migration}
        )

    async def cancel(self, migration: str, *, idempotency_key: str | None = None) -> FieldMigration:
        return await self._client.request(
            "migrations_cancel",
            cast=FieldMigration,
            path={"migration_id": migration},
            idempotency_key=idempotency_key,
        )
