from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

from typing_extensions import Unpack

from ..._pagination import AsyncPaginator
from ...models import Webhook, WebhookDelivery, WebhookDeliveryDetail, WebhookWithSecret
from ...params import WebhookCreate, WebhookUpdate
from ...webhooks import WebhookEvent, unwrap
from .._client import AsyncAPIClient
from ._resource import AsyncResource


class AsyncWebhooks(AsyncResource):
    """Webhooks of the key's project. `webhook` is a webhook ID (`wh_...`)."""

    def __init__(self, client: AsyncAPIClient) -> None:
        super().__init__(client)
        self.deliveries = AsyncDeliveries(client)

    def list(
        self, *, limit: int | None = None, cursor: str | None = None
    ) -> AsyncPaginator[Webhook]:
        return self._client.paginate(
            "webhooks_list", item=Webhook, query={"limit": limit, "cursor": cursor}
        )

    async def get(self, webhook: str) -> Webhook:
        return await self._client.request(
            "webhooks_get", cast=Webhook, path={"webhook_id": webhook}
        )

    async def create(
        self, *, idempotency_key: str | None = None, **params: Unpack[WebhookCreate]
    ) -> WebhookWithSecret:
        """Subscribes a URL. The response is the only time `secret` is shown."""
        return await self._client.request(
            "webhooks_create",
            cast=WebhookWithSecret,
            body=params,
            idempotency_key=idempotency_key,
        )

    async def update(
        self, webhook: str, *, idempotency_key: str | None = None, **params: Unpack[WebhookUpdate]
    ) -> Webhook:
        return await self._client.request(
            "webhooks_update",
            cast=Webhook,
            path={"webhook_id": webhook},
            body=params,
            idempotency_key=idempotency_key,
        )

    async def delete(self, webhook: str, *, idempotency_key: str | None = None) -> Webhook:
        return await self._client.request(
            "webhooks_delete",
            cast=Webhook,
            path={"webhook_id": webhook},
            idempotency_key=idempotency_key,
        )

    async def rotate_secret(
        self, webhook: str, *, idempotency_key: str | None = None
    ) -> WebhookWithSecret:
        """A new signing secret; the old one stops working at once."""
        return await self._client.request(
            "webhooks_rotate_secret",
            cast=WebhookWithSecret,
            path={"webhook_id": webhook},
            idempotency_key=idempotency_key,
        )

    async def test(self, webhook: str, *, idempotency_key: str | None = None) -> WebhookDelivery:
        """Sends a `webhook.test` event to the URL."""
        return await self._client.request(
            "webhooks_test",
            cast=WebhookDelivery,
            path={"webhook_id": webhook},
            idempotency_key=idempotency_key,
        )

    def unwrap(
        self,
        body: str | bytes,
        headers: Mapping[str, str],
        *,
        secret: str,
        tolerance: int = 300,
    ) -> WebhookEvent:
        """Checks a webhook request's signature and returns its event (see
        `nohead.webhooks.unwrap`, which needs no client)."""
        return unwrap(body, headers, secret=secret, tolerance=tolerance)


class AsyncDeliveries(AsyncResource):
    """Delivery attempts of a webhook's events."""

    def list(
        self,
        webhook: str,
        *,
        status: Literal["pending", "succeeded", "failed"] | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> AsyncPaginator[WebhookDelivery]:
        return self._client.paginate(
            "webhook_deliveries_list",
            item=WebhookDelivery,
            path={"webhook_id": webhook},
            query={"status": status, "limit": limit, "cursor": cursor},
        )

    async def get(self, delivery: str) -> WebhookDeliveryDetail:
        return await self._client.request(
            "webhook_deliveries_get", cast=WebhookDeliveryDetail, path={"delivery_id": delivery}
        )

    async def retry(self, delivery: str, *, idempotency_key: str | None = None) -> WebhookDelivery:
        """Sends the event again."""
        return await self._client.request(
            "webhook_deliveries_retry",
            cast=WebhookDelivery,
            path={"delivery_id": delivery},
            idempotency_key=idempotency_key,
        )
