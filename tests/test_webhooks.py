from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import warnings

import pytest

from nohead import Asset, NoheadWarning, WebhookVerificationError
from nohead.models import AssetEventDataAsset
from nohead.webhooks import unwrap

from .conftest import Make, record

NOW = 1790942400  # 2026-10-02 12:00 UTC

SECRET = "whsec_" + base64.b64encode(b"a-very-secret-key").decode()
OTHER_SECRET = "whsec_" + base64.b64encode(b"another-secret-key").decode()
BODY = json.dumps(
    {
        "id": "wev_1",
        "object": "event",
        "type": "record.published",
        "created_at": "2026-10-02T12:00:00.000Z",
        "project_id": "prj_1",
        "actor": {"type": "api_key", "id": "key_1", "name": "Importer"},
        "via": "sdk",
        "data": {"record": record("rec_1", title="Hi"), "revision": 2, "revision_id": "rev_1"},
    }
)


@pytest.fixture(autouse=True)
def frozen_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(time, "time", lambda: float(NOW))


def sign(
    body: str, timestamp: int = NOW, id: str = "msg_1", secret: str = SECRET
) -> dict[str, str]:
    key = base64.b64decode(secret.removeprefix("whsec_"))
    digest = hmac.new(key, f"{id}.{timestamp}.{body}".encode(), hashlib.sha256).digest()
    return {
        "webhook-id": id,
        "webhook-timestamp": str(timestamp),
        "webhook-signature": "v1," + base64.b64encode(digest).decode(),
    }


def test_the_standard_webhooks_spec_example(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(time, "time", lambda: 1614265330.0)
    headers = {
        "webhook-id": "msg_p5jXN8AQM9LWM0D4loKWxJek",
        "webhook-timestamp": "1614265330",
        "webhook-signature": "v1,g0hM9SsE+OTPJTGt/tmIKtSyZlE3uFJELVlNIOLJ1OE=",
    }
    secret = "whsec_MfKQ9r8GKYqrTwjUPD8ILPZIo2LaLaSw"
    # The signature matches; its body just isn't a Nohead event, so it comes unvalidated.
    with pytest.warns(NoheadWarning):
        event = unwrap('{"test": 2432232314}', headers, secret=secret)
    assert event.model_extra == {"test": 2432232314}
    assert (event.record, event.revision, event.draft_id) == (None, None, None)
    with pytest.raises(WebhookVerificationError, match="No webhook signature matches"):
        unwrap('{"test": 2432232315}', headers, secret=secret)


def test_returns_the_event() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        event = unwrap(BODY, sign(BODY), secret=SECRET)
    assert event.type == "record.published"
    assert (event.actor.id, event.via) == ("key_1", "sdk")
    assert event.revision == 2
    assert event.record is not None and event.record.data["title"] == "Hi"
    assert event.asset is None


def test_draft_events_name_the_draft_once_it_is_gone() -> None:
    body = (
        '{"id":"wev_2","object":"event","type":"draft.discarded",'
        '"created_at":"2026-10-18T12:00:00.000Z","project_id":"prj_1",'
        '"actor":{"type":"user","id":"usr_1","name":"Ada"},"via":"ui",'
        '"data":{"draft":null,"draft_id":"drf_1","record_id":"rec_1"}}'
    )
    event = unwrap(body, sign(body), secret=SECRET)
    assert event.draft is None
    assert event.draft_id == "drf_1"
    assert event.record_id == "rec_1"


def event(type: str, data: dict[str, object], **envelope: object) -> str:
    body = {
        "id": "wev_3",
        "object": "event",
        "type": type,
        "created_at": "2026-10-18T12:00:00.000Z",
        "project_id": "prj_1",
        "actor": {"type": "system", "id": None, "name": "System"},
        "via": None,
        "data": data,
    }
    return json.dumps(body | envelope)


def test_a_purged_asset_is_only_its_id() -> None:
    body = event("asset.purged", {"asset": {"id": "ast_1", "object": "asset"}})
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        asset = unwrap(body, sign(body), secret=SECRET).asset
    assert isinstance(asset, AssetEventDataAsset)
    assert asset.id == "ast_1"


def test_parts_that_do_not_match_come_unvalidated() -> None:
    body = event("asset.created", {"asset": {"id": "ast_1", "object": "asset", "status": 7}})
    received = unwrap(body, sign(body), secret=SECRET)
    with pytest.warns(NoheadWarning):
        asset = received.asset
    assert isinstance(asset, Asset)
    assert (asset.id, asset.status) == ("ast_1", 7)


def test_an_envelope_that_does_not_match_comes_unvalidated() -> None:
    body = event("record.published", {"record": None}, created_at="yesterday", via=["api"])
    with pytest.warns(NoheadWarning):
        received = unwrap(body, sign(body), secret=SECRET)
    assert (received.id, received.created_at) == ("wev_3", "yesterday")
    assert received.record is None


def test_field_events_name_the_field() -> None:
    collection = {"id": "col_1", "object": "collection", "slug": "posts", "name": "Posts"}
    body = event(
        "field.updated",
        {
            "collection": collection | {"schema_version": 3, "deleted_at": None},
            "field_id": "fld_1",
            "schema_change": None,
        },
    )
    received = unwrap(body, sign(body), secret=SECRET)
    assert received.field_id == "fld_1"
    assert received.collection is not None and received.collection["object"] == "collection"


def test_any_header_case_bytes_and_several_signatures() -> None:
    headers = {k.title(): v for k, v in sign(BODY).items()}
    headers["Webhook-Signature"] = "v1,bm90LWl0 " + headers["Webhook-Signature"]
    assert unwrap(BODY.encode(), headers, secret=SECRET).id == "wev_1"


def test_from_either_client(make: Make) -> None:
    nohead, _ = make([])
    assert nohead.webhooks.unwrap(BODY, sign(BODY), secret=SECRET).project_id == "prj_1"


def test_accepts_timestamps_up_to_the_tolerance_off() -> None:
    for timestamp in (NOW - 300, NOW + 300):
        assert unwrap(BODY, sign(BODY, timestamp), secret=SECRET).id == "wev_1"
    old = sign(BODY, NOW - 600)
    assert unwrap(BODY, old, secret=SECRET, tolerance=600).id == "wev_1"
    with pytest.raises(WebhookVerificationError):
        unwrap(BODY, old, secret=SECRET, tolerance=599)


@pytest.mark.parametrize(
    ("body", "headers"),
    [
        (BODY.replace("Hi", "Bye"), sign(BODY)),
        (BODY, sign(BODY) | {"webhook-id": "msg_2"}),
        (BODY, {k: v.replace("v1,", "v2,") for k, v in sign(BODY).items()}),
        (BODY, sign(BODY, secret=OTHER_SECRET)),
        (BODY, sign(BODY, NOW - 301)),
        (BODY, sign(BODY, NOW + 301)),
        (BODY, sign(BODY) | {"webhook-timestamp": "soon"}),
        (BODY, {}),
        ("not json", sign("not json")),
    ],
    ids=[
        "changed body",
        "changed webhook-id",
        "signature of another version",
        "wrong secret",
        "old timestamp",
        "future timestamp",
        "timestamp not a number",
        "missing headers",
        "body not json",
    ],
)
def test_rejects(body: str, headers: dict[str, str]) -> None:
    with pytest.raises(WebhookVerificationError):
        unwrap(body, headers, secret=SECRET)


def test_rejects_a_secret_that_is_not_base64() -> None:
    with pytest.raises(WebhookVerificationError, match="not base64"):
        unwrap(BODY, sign(BODY), secret="whsec_not base64!")
