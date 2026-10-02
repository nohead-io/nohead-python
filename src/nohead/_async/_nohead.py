# pyright: reportPrivateUsage=false
from __future__ import annotations

from collections.abc import Mapping, Sequence
from types import TracebackType
from typing import Literal, Self

import httpx

from .. import _base
from .._pagination import AsyncPaginator
from ..models import Record, SearchResultsMeta
from ._client import AsyncAPIClient
from .resources.assets import AsyncAssets
from .resources.other import AsyncAuditEvents, AsyncFeatureFlags, AsyncHealth, AsyncMe
from .resources.records import AsyncRecords
from .resources.schema import AsyncCollections, AsyncFields, AsyncMigrations
from .resources.webhooks import AsyncWebhooks


class AsyncNohead:
    """An async client for the Nohead API, authenticated with a project API key.

    async with AsyncNohead() as nohead:  # NOHEAD_API_KEY
        async for post in nohead.records.list("posts"):
            print(post.data["title"])
    """

    records: AsyncRecords
    collections: AsyncCollections
    fields: AsyncFields
    migrations: AsyncMigrations
    assets: AsyncAssets
    webhooks: AsyncWebhooks
    audit_events: AsyncAuditEvents
    feature_flags: AsyncFeatureFlags
    me: AsyncMe
    health: AsyncHealth

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        project_id: str | None = None,
        max_retries: int = 2,
        timeout: float = 60.0,
        headers: Mapping[str, str] | None = None,
        warnings: bool = True,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        """
        Args:
            api_key: A project API key (`sk_live_...`). Defaults to NOHEAD_API_KEY.
            base_url: Defaults to NOHEAD_API_URL, else https://api.nohead.io.
            project_id: The key's project. Looked up once with GET /v1/me when omitted.
            max_retries: Retries of failed requests (see the README, "Retries").
            timeout: Seconds per attempt.
            headers: Headers added to every request.
            warnings: Warn about deprecated operations and plan usage (once each).
            http_client: An httpx client to send requests with (proxies, transports).
        """
        settings = _base.settings(
            api_key=api_key,
            base_url=base_url,
            project_id=project_id,
            max_retries=max_retries,
            timeout=timeout,
            headers=headers,
            warnings=warnings,
        )
        self._setup(AsyncAPIClient(settings, http_client))

    def _setup(self, client: AsyncAPIClient) -> None:
        self._client = client
        self.records = AsyncRecords(client)
        self.collections = AsyncCollections(client)
        self.fields = AsyncFields(client)
        self.migrations = AsyncMigrations(client)
        self.assets = AsyncAssets(client)
        self.webhooks = AsyncWebhooks(client)
        self.audit_events = AsyncAuditEvents(client)
        self.feature_flags = AsyncFeatureFlags(client)
        self.me = AsyncMe(client)
        self.health = AsyncHealth(client)

    def with_options(
        self,
        *,
        timeout: float | None = None,
        max_retries: int | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Self:
        """A client with other settings that shares this one's connections:
        `nohead.with_options(timeout=5).records.get(id)`."""
        current = self._client.settings
        settings = _base.Settings(
            api_key=current.api_key,
            base_url=current.base_url,
            project_id=current.project_id,
            max_retries=current.max_retries if max_retries is None else max_retries,
            timeout=current.timeout if timeout is None else timeout,
            headers={**current.headers, **(headers or {})},
            warnings=current.warnings,
        )
        copy = object.__new__(type(self))
        copy._setup(self._client.copy(settings))
        return copy

    def search(
        self,
        query: str,
        *,
        collections: Sequence[str] | None = None,
        status: Literal["draft", "published"] | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> AsyncPaginator[Record, SearchResultsMeta]:
        """Full-text search across the key's project (or some of its collections),
        most relevant first, through the first 1,000 hits."""
        return self._client.paginate(
            "projects_search",
            item=Record,
            meta=SearchResultsMeta,
            query={
                "q": query,
                "collections": collections,
                "filter": {"status": status},
                "limit": limit,
                "cursor": cursor,
            },
        )

    async def close(self) -> None:
        """Closes the connections (unless an `http_client` was passed in)."""
        await self._client.close()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.close()
