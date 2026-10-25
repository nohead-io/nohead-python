from __future__ import annotations

from typing import Literal

from ..._base import one_or_in
from ..._pagination import AsyncPaginator
from ...models import AuditEvent, Principal
from ...models import FeatureFlags as FeatureFlagValues
from ...models import Health as HealthStatus
from ...types import AuditEventFilter
from ._resource import AsyncResource


class AsyncAuditEvents(AsyncResource):
    """The project's activity log, newest first. Needs the `audit:read` scope."""

    def list(
        self,
        *,
        filter: AuditEventFilter | None = None,
        sort: Literal["created_at", "-created_at"] | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> AsyncPaginator[AuditEvent]:
        """`filter` takes `type` (exact, or a `record.*` prefix), `resource_type` (one, or
        a list of several), `resource_id`, `actor_type`, `actor_id` and a `created_at`
        range: `filter={"type": "record.*", "created_at": {"gte": since}}`."""
        # `resource_type` as the API takes several.
        query_filter = filter and {
            **filter,
            "resource_type": one_or_in(filter.get("resource_type")),
        }
        return self._client.paginate(
            "audit_events_list",
            item=AuditEvent,
            query={"filter": query_filter, "sort": sort, "limit": limit, "cursor": cursor},
        )


class AsyncFeatureFlags(AsyncResource):
    async def list(self) -> FeatureFlagValues:
        """Flags evaluated for the key's project."""
        return await self._client.request("feature_flags_list", cast=FeatureFlagValues)


class AsyncMe(AsyncResource):
    async def get(self) -> Principal:
        """The API key: its project, scopes, `published_only` and expiry."""
        return await self._client.request("me_get", cast=Principal)


class AsyncHealth(AsyncResource):
    async def check(self) -> HealthStatus:
        return await self._client.request("health_check", cast=HealthStatus)
