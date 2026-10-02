from __future__ import annotations

from typing import Literal

from ..._pagination import AsyncPaginator
from ...models import AuditEvent, Principal
from ...models import FeatureFlags as FeatureFlagValues
from ...models import Health as HealthStatus
from ...types import RecordFilter
from ._resource import AsyncResource


class AsyncAuditEvents(AsyncResource):
    """The project's activity log, newest first. Needs the `audit:read` scope."""

    def list(
        self,
        *,
        filter: RecordFilter | None = None,
        sort: Literal["id", "-id"] | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> AsyncPaginator[AuditEvent]:
        """`filter` takes `action` (exact, or a `record.*` prefix), `resource_type`,
        `resource_id`, `actor_type`, `actor_id`, `since` and `until`."""
        return self._client.paginate(
            "audit_events_list_for_project",
            item=AuditEvent,
            query={"filter": filter, "sort": sort, "limit": limit, "cursor": cursor},
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
