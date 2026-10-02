from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

import pytest

from nohead import WebhookVerificationError
from nohead.webhooks import unwrap

from .conftest import make_sync, record

SECRET = "whsec_" + base64.b64encode(b"a-very-secret-key").decode()
BODY = json.dumps(
    {
        "id": "wev_1",
        "object": "event",
        "type": "record.published",
        "created_at": "2026-10-02T12:00:00.000Z",
        "project_id": "prj_1",
        "data": {"record": record("rec_1", title="Hi"), "revision": 2, "revision_id": "rev_1"},
    }
)


def sign(body: str, timestamp: int | None = None, id: str = "msg_1") -> dict[str, str]:
    timestamp = int(time.time()) if timestamp is None else timestamp
    key = base64.b64decode(SECRET.removeprefix("whsec_"))
    digest = hmac.new(key, f"{id}.{timestamp}.{body}".encode(), hashlib.sha256).digest()
    return {
        "webhook-id": id,
        "webhook-timestamp": str(timestamp),
        "webhook-signature": "v1," + base64.b64encode(digest).decode(),
    }


def test_returns_the_event() -> None:
    event = unwrap(BODY, sign(BODY), secret=SECRET)
    assert event.type == "record.published"
    assert event.revision == 2
    assert event.record is not None and event.record.data["title"] == "Hi"
    assert event.asset is None


def test_any_header_case_bytes_and_several_signatures() -> None:
    headers = {k.title(): v for k, v in sign(BODY).items()}
    headers["Webhook-Signature"] = "v1,bm90LWl0 " + headers["Webhook-Signature"]
    assert unwrap(BODY.encode(), headers, secret=SECRET).id == "wev_1"


def test_from_the_client() -> None:
    nohead, _ = make_sync([])
    assert nohead.webhooks.unwrap(BODY, sign(BODY), secret=SECRET).project_id == "prj_1"


@pytest.mark.parametrize(
    ("body", "headers"),
    [
        (BODY.replace("Hi", "Bye"), sign(BODY)),
        (BODY, sign(BODY.replace("Hi", "x"))),
        (BODY, sign(BODY, int(time.time()) - 600)),
        (BODY, {}),
    ],
    ids=["changed body", "wrong signature", "old timestamp", "missing headers"],
)
def test_rejects(body: str, headers: dict[str, str]) -> None:
    with pytest.raises(WebhookVerificationError):
        unwrap(body, headers, secret=SECRET)
