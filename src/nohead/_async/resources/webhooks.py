from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

from typing_extensions import Unpack

from ..._pagination import AsyncPaginator
from ...models import (
    Webhook,
    WebhookDelivery,
    WebhookDeliveryDetail,
    WebhookSecret,
    WebhookSecretWithValue,
    WebhookWithSecret,
)
from ...params import WebhookCreate, WebhookUpdate
from ...webhooks import WebhookEvent, unwrap
from .._client import AsyncAPIClient
from ._resource import AsyncResource


class AsyncWebhooks(AsyncResource):
    """Webhooks of the key's project. `webhook` is a webhook ID (`wh_...`)."""

    def __init__(self, client: AsyncAPIClient) -> None:
        super().__init__(client)
        self.deliveries = AsyncDeliveries(client)
        self.secrets = AsyncSecrets(client)

    def list(
        self, *, deleted: bool | None = None, limit: int | None = None, cursor: str | None = None
    ) -> AsyncPaginator[Webhook]:
        """`deleted=True` lists deleted webhooks instead (restorable until their
        `purge_after`)."""
        return self._client.paginate(
            "webhooks_list",
            item=Webhook,
            query={"filter": {"deleted": deleted}, "limit": limit, "cursor": cursor},
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
        """Soft-deletes the webhook: `restore` brings it back until its `purge_after`."""
        return await self._client.request(
            "webhooks_delete",
            cast=Webhook,
            path={"webhook_id": webhook},
            idempotency_key=idempotency_key,
        )

    async def restore(self, webhook: str, *, idempotency_key: str | None = None) -> Webhook:
        return await self._client.request(
            "webhooks_restore",
            cast=Webhook,
            path={"webhook_id": webhook},
            idempotency_key=idempotency_key,
        )

    async def rotate_secret(
        self, webhook: str, *, idempotency_key: str | None = None
    ) -> WebhookSecretWithValue:
        """A new signing secret (`secret`, shown only here). The ones before it keep
        signing for 24 hours, so receivers can switch without rejecting deliveries;
        `secrets.retire` ends one sooner."""
        return await self._client.request(
            "webhooks_rotate_secret",
            cast=WebhookSecretWithValue,
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
            query={"filter": {"status": status}, "limit": limit, "cursor": cursor},
        )

    async def get(self, delivery: str) -> WebhookDeliveryDetail:
        return await self._client.request(
            "webhook_deliveries_get", cast=WebhookDeliveryDetail, path={"delivery_id": delivery}
        )

    async def retry(self, delivery: str, *, idempotency_key: str | None = None) -> WebhookDelivery:
        """Sends the event again now, as a new attempt."""
        return await self._client.request(
            "webhook_deliveries_retry",
            cast=WebhookDelivery,
            path={"delivery_id": delivery},
            idempotency_key=idempotency_key,
        )


class AsyncSecrets(AsyncResource):
    """A webhook's signing secrets. `secret` is a secret ID (`whs_...`)."""

    def list(
        self, webhook: str, *, limit: int | None = None, cursor: str | None = None
    ) -> AsyncPaginator[WebhookSecret]:
        """Those signing deliveries now, oldest first, without their values."""
        return self._client.paginate(
            "webhook_secrets_list",
            item=WebhookSecret,
            path={"webhook_id": webhook},
            query={"limit": limit, "cursor": cursor},
        )

    async def retire(self, secret: str, *, idempotency_key: str | None = None) -> WebhookSecret:
        """Stops signing with it now. The newest can't be retired: rotate first."""
        return await self._client.request(
            "webhook_secrets_retire",
            cast=WebhookSecret,
            path={"secret_id": secret},
            idempotency_key=idempotency_key,
        )
