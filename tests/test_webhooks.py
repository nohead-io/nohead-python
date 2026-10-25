from __future__ import annotations

import base64
import json
import time
import warnings
from datetime import UTC, datetime, tzinfo

import pytest
import standardwebhooks
import standardwebhooks.webhooks

from nohead import Asset, NoheadWarning, WebhookVerificationError
from nohead.models import AssetEventDataAsset
from nohead.webhooks import unwrap

from .conftest import Make, record

NOW = 1790942400  # 2026-10-02 12:00 UTC

SECRET = "whsec_" + base64.b64encode(b"a-very-secret-key").decode()
OTHER_SECRET = "whsec_" + base64.b64encode(b"another-secret-key").decode()
# int() reads these too: ١٧٩٠٩٤٢٤٠٠ is NOW.
ARABIC_DIGITS = str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")
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


class FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz: tzinfo | None = None) -> FrozenDatetime:
        return cls.fromtimestamp(NOW, tz)


@pytest.fixture(autouse=True)
def frozen_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(time, "time", lambda: float(NOW))
    # The Standard Webhooks library's clock, for its verify().
    monkeypatch.setattr(standardwebhooks.webhooks, "datetime", FrozenDatetime)


def sign(
    body: str, timestamp: int = NOW, id: str = "msg_1", secret: str = SECRET
) -> dict[str, str]:
    """Signs as a sender does, with the official Standard Webhooks library."""
    sent_at = datetime.fromtimestamp(timestamp, UTC)
    return {
        "webhook-id": id,
        "webhook-timestamp": str(timestamp),
        "webhook-signature": standardwebhooks.Webhook(secret).sign(id, sent_at, body),
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
        (BODY, sign(BODY) | {"webhook-signature": "v1,ü"}),
        (BODY, sign(BODY) | {"webhook-signature": "v1,\udc80"}),
        (BODY, sign(BODY) | {"webhook-id": "msg_\udc80"}),
        (BODY, sign(BODY) | {"webhook-timestamp": str(NOW).translate(ARABIC_DIGITS)}),
        (BODY + "\udc80", sign(BODY)),
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
        "signature not ascii",
        "signature with a lone surrogate",
        "webhook-id with a lone surrogate",
        "timestamp in other digits",
        "body with a lone surrogate",
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
    with pytest.raises(WebhookVerificationError, match="not base64"):
        unwrap(BODY, sign(BODY), secret="whsec_ünicode")


# The API's secrets are 32 bytes; SECRET's are 17.
API_SECRET = "whsec_" + base64.b64encode(bytes(range(32))).decode()
# Sent as UTF-8, unescaped.
NON_ASCII_BODY = json.dumps(
    json.loads(BODY)
    | {
        "actor": {"type": "user", "id": "usr_1", "name": "Zoë Ångström"},
        "data": {"record": record("rec_1", title="Grüße aus 東京 🌸"), "revision": 2},
    },
    ensure_ascii=False,
)


@pytest.mark.parametrize("secret", [SECRET, API_SECRET], ids=["secret", "api secret"])
@pytest.mark.parametrize("body", [BODY, NON_ASCII_BODY], ids=["ascii", "non-ascii"])
@pytest.mark.parametrize("as_bytes", [False, True], ids=["str", "bytes"])
def test_accepts_what_the_standard_webhooks_library_signs(
    secret: str, body: str, as_bytes: bool
) -> None:
    headers = sign(body, secret=secret)
    received = body.encode() if as_bytes else body
    sent = json.loads(body)
    assert standardwebhooks.Webhook(secret).verify(received, headers) == sent
    event = unwrap(received, headers, secret=secret)
    assert event.actor.name == sent["actor"]["name"]
    assert event.record is not None
    assert event.record.data["title"] == sent["data"]["record"]["data"]["title"]


@pytest.mark.parametrize(
    "order",
    [[0, 1, 2], [2, 1, 0], [1, 0, 2]],
    ids=["matching first", "matching last", "matching in the middle"],
)
def test_accepts_one_matching_signature_among_several(order: list[int]) -> None:
    # As during a secret rotation: one signature per secret, and one of another version.
    signatures = [
        sign(NON_ASCII_BODY, secret=API_SECRET)["webhook-signature"],
        sign(NON_ASCII_BODY, secret=OTHER_SECRET)["webhook-signature"].replace("v1,", "v2,"),
        sign(NON_ASCII_BODY, secret=OTHER_SECRET)["webhook-signature"],
    ]
    headers = sign(NON_ASCII_BODY, secret=API_SECRET) | {
        "webhook-signature": " ".join(signatures[i] for i in order)
    }
    assert standardwebhooks.Webhook(API_SECRET).verify(NON_ASCII_BODY, headers)
    assert unwrap(NON_ASCII_BODY, headers, secret=API_SECRET).id == "wev_1"
    assert unwrap(NON_ASCII_BODY, headers, secret=OTHER_SECRET).id == "wev_1"


@pytest.mark.parametrize(
    ("body", "headers", "secret"),
    [
        (NON_ASCII_BODY.replace("東京", "大阪"), sign(NON_ASCII_BODY), SECRET),
        (NON_ASCII_BODY.replace("ë", "e"), sign(NON_ASCII_BODY), SECRET),
        (BODY.replace("Hi", "Bye"), sign(BODY), SECRET),
        (BODY, sign(BODY), OTHER_SECRET),
        (BODY, sign(BODY, secret=API_SECRET), SECRET),
        (BODY, sign(BODY, NOW - 301), SECRET),
        (BODY, sign(BODY, NOW - 86400), SECRET),
        (BODY, sign(BODY, NOW + 301), SECRET),
        (BODY, sign(BODY) | {"webhook-id": "msg_2"}, SECRET),
        (BODY, {k: v.replace("v1,", "v2,") for k, v in sign(BODY).items()}, SECRET),
        (BODY, {k: v for k, v in sign(BODY).items() if k != "webhook-signature"}, SECRET),
    ],
    ids=[
        "tampered non-ascii body",
        "non-ascii body with its accent dropped",
        "tampered body",
        "wrong secret",
        "another secret's signature",
        "old timestamp",
        "day-old timestamp",
        "future timestamp",
        "changed webhook-id",
        "only another version's signature",
        "no signature",
    ],
)
def test_rejects_what_the_standard_webhooks_library_rejects(
    body: str, headers: dict[str, str], secret: str
) -> None:
    with pytest.raises(standardwebhooks.WebhookVerificationError):
        standardwebhooks.Webhook(secret).verify(body, headers)
    # Only WebhookVerificationError: any other exception fails the test.
    with pytest.raises(WebhookVerificationError):
        unwrap(body, headers, secret=secret)
