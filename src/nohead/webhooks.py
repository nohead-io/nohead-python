"""Verifying webhook requests (Standard Webhooks), with or without a client:

from nohead.webhooks import unwrap

event = unwrap(request.body, request.headers, secret=os.environ["NOHEAD_WEBHOOK_SECRET"])
if event.type == "record.published":
    print(event.record.id)
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import time
from collections.abc import Mapping
from datetime import datetime
from typing import Any, TypeVar

from ._errors import WebhookVerificationError
from .models import Asset, Collection, NoheadModel, Record, SchemaChange, Webhook

__all__ = ["WebhookEvent", "unwrap"]

M = TypeVar("M", bound=NoheadModel)


class WebhookEvent(NoheadModel):
    """A webhook request's body. `data` depends on `type`; the properties below parse
    the parts each type carries (None when this event has no such part)."""

    id: str
    object: str
    type: str
    """`record.created`, `record.updated`, `record.deleted`, `record.published`,
    `record.unpublished`, `asset.created`, `asset.deleted`, `schema.changed` or
    `webhook.test`."""
    created_at: datetime
    project_id: str
    data: dict[str, Any]

    @property
    def record(self) -> Record | None:
        """`record.*` events: the record after the change."""
        return self._part("record", Record)

    @property
    def revision(self) -> int | None:
        """`record.*` events: the record's revision number."""
        value = self.data.get("revision")
        return value if isinstance(value, int) else None

    @property
    def revision_id(self) -> str | None:
        value = self.data.get("revision_id")
        return value if isinstance(value, str) else None

    @property
    def asset(self) -> Asset | None:
        """`asset.*` events."""
        return self._part("asset", Asset)

    @property
    def collection(self) -> Collection | None:
        """`schema.changed` events."""
        return self._part("collection", Collection)

    @property
    def schema_change(self) -> SchemaChange | None:
        """`schema.changed` events."""
        return self._part("schema_change", SchemaChange)

    @property
    def webhook(self) -> Webhook | None:
        """`webhook.test` events."""
        return self._part("webhook", Webhook)

    def _part(self, key: str, model: type[M]) -> M | None:
        value = self.data.get(key)
        return model.model_validate(value) if isinstance(value, dict) else None


def unwrap(
    body: str | bytes, headers: Mapping[str, str], *, secret: str, tolerance: int = 300
) -> WebhookEvent:
    """Checks a webhook request's signature and timestamp and returns its event.

    Pass the raw body exactly as received: parsing and re-serializing JSON changes the
    bytes, and the signature with them. Raises WebhookVerificationError when anything
    does not match.
    """
    lower = {key.lower(): value for key, value in headers.items()}
    webhook_id = lower.get("webhook-id")
    timestamp = lower.get("webhook-timestamp")
    signatures = lower.get("webhook-signature")
    if not webhook_id or not timestamp or not signatures:
        raise WebhookVerificationError(
            "Missing webhook-id, webhook-timestamp or webhook-signature header"
        )
    try:
        sent_at = int(timestamp)
    except ValueError:
        raise WebhookVerificationError("The webhook timestamp is not a number") from None
    if abs(time.time() - sent_at) > tolerance:
        raise WebhookVerificationError("The webhook timestamp is too far from the current time")

    raw = body.encode() if isinstance(body, str) else body
    try:
        key = base64.b64decode(secret.removeprefix("whsec_"), validate=True)
    except binascii.Error:
        raise WebhookVerificationError("The webhook secret is not base64") from None
    signed = webhook_id.encode() + b"." + timestamp.encode() + b"." + raw
    expected = base64.b64encode(hmac.new(key, signed, hashlib.sha256).digest()).decode()
    for entry in signatures.split(" "):
        version, _, signature = entry.partition(",")
        if version == "v1" and hmac.compare_digest(signature, expected):
            try:
                return WebhookEvent.model_validate(json.loads(raw))
            except ValueError:
                raise WebhookVerificationError("The webhook body is not a JSON event") from None
    raise WebhookVerificationError("No webhook signature matches")
