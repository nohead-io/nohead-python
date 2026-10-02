from __future__ import annotations

from datetime import UTC, datetime

import pytest

from .conftest import json_response, make_async, make_sync, page, record


def test_encodes_path_parameters() -> None:
    nohead, calls = make_sync([page([], None)])
    nohead.records.list("my posts/1")
    assert calls.calls[0].url.raw_path.startswith(b"/v1/collections/my%20posts%2F1/records")


def test_serializes_filters_sorts_and_expansions() -> None:
    nohead, calls = make_sync([page([], None)])
    nohead.records.list(
        "posts",
        filter={
            "status": "published",
            "featured": True,
            "views": 3,
            "published_after": datetime(2026, 1, 1, tzinfo=UTC),
            "skip": None,
        },
        sort="-published_at",
        expand=["author", "tags"],
        limit=50,
    )
    params = calls.calls[0].url.params
    assert params["filter[status]"] == "published"
    assert params["filter[featured]"] == "true"
    assert params["filter[views]"] == "3"
    assert params["filter[published_after]"] == "2026-01-01T00:00:00Z"
    assert "filter[skip]" not in params
    assert params["sort"] == "-published_at"
    assert params["expand"] == "author,tags"
    assert params["limit"] == "50"
    assert "cursor" not in params


def test_sends_bodies_as_json() -> None:
    nohead, calls = make_sync([json_response(201, record("rec_1"))])
    created = nohead.records.create("posts", data={"title": "Hi"})
    assert created.id == "rec_1"
    assert calls.calls[0].method == "POST"
    assert calls.calls[0].headers["content-type"] == "application/json"
    assert calls.body(0) == {"data": {"title": "Hi"}}


def test_serializes_dates_in_bodies() -> None:
    nohead, calls = make_sync([json_response(200, record("rec_1"))])
    nohead.records.schedule("rec_1", publish_at=datetime(2027, 1, 1, 9, tzinfo=UTC))
    assert calls.body(0) == {"publish_at": "2027-01-01T09:00:00Z"}


def test_clears_scheduled_times() -> None:
    nohead, calls = make_sync([json_response(200, record("rec_1"))])
    nohead.records.schedule("rec_1", clear=["unpublish_at"])
    assert calls.body(0) == {"unpublish_at": None}


def test_idempotency_keys_on_writes_only() -> None:
    nohead, calls = make_sync([json_response(200, record("rec_1"))])
    nohead.records.publish("rec_1")
    nohead.records.publish("rec_1")
    nohead.records.get("rec_1")
    keys = [c.headers.get("idempotency-key") for c in calls.calls]
    assert keys[0] and len(keys[0]) == 36
    assert keys[1] != keys[0]
    assert keys[2] is None


def test_uses_the_callers_idempotency_key() -> None:
    nohead, calls = make_sync([json_response(201, record("rec_1"))])
    nohead.records.create("posts", data={}, idempotency_key="import-42")
    assert calls.calls[0].headers["idempotency-key"] == "import-42"


def test_if_match_from_a_revision_or_a_record() -> None:
    nohead, calls = make_sync([json_response(200, record("rec_1"))])
    post = nohead.records.update("rec_1", data={"title": None}, if_match=3)
    nohead.records.publish("rec_1", if_match=post)
    assert [c.headers["if-match"] for c in calls.calls] == ['"3"', '"1"']


def test_change_note() -> None:
    nohead, calls = make_sync([json_response(200, record("rec_1"))])
    nohead.records.delete("rec_1", change_note="Duplicate")
    assert calls.calls[0].headers["nohead-change-note"] == "Duplicate"


@pytest.mark.filterwarnings("ignore::nohead.NoheadWarning")
def test_dry_runs_are_query_parameters() -> None:
    preview = {"object": "field_migration_preview", "field_id": "fld_1"}
    nohead, calls = make_sync([json_response(200, preview)])
    nohead.fields.migrate("fld_1", type="integer", dry_run=True)
    assert calls.calls[0].url.params["dry_run"] == "true"
    assert calls.body(0) == {"type": "integer"}


def test_diff_names_its_revisions() -> None:
    diff = {"object": "record_diff", "record_id": "rec_1", "from": 1, "to": 2, "changes": []}
    nohead, calls = make_sync([json_response(200, diff)])
    result = nohead.records.diff("rec_1", 1, 2)
    assert (result.from_, result.to) == (1, 2)
    assert dict(calls.calls[0].url.params) == {"from": "1", "to": "2"}


def test_keeps_unknown_fields_and_values() -> None:
    body = record("rec_1", title="Hi") | {"status": "archived", "brand_new": True}
    nohead, _ = make_sync([json_response(200, body)])
    post = nohead.records.get("rec_1")
    assert post.status == "archived"
    assert post.model_extra == {"brand_new": True}
    assert post.created_at == datetime(2026, 10, 2, 12, tzinfo=UTC)


async def test_async_requests() -> None:
    nohead, calls = make_async([json_response(201, record("rec_1"))])
    created = await nohead.records.create("posts", data={"title": "Hi"}, change_note="Import")
    assert created.data == {"title": "Hi"} or created.id == "rec_1"
    assert calls.calls[0].headers["nohead-change-note"] == "Import"
    assert calls.body(0) == {"data": {"title": "Hi"}}


def test_builds_responses_that_do_not_match_the_models() -> None:
    odd = record("rec_1") | {"revision": "not a number", "schedule": {"publish_at": None}}
    nohead, _ = make_sync([json_response(200, odd)])
    with pytest.warns(nohead_warning()):
        post = nohead.records.get("rec_1")
    assert post.id == "rec_1"
    assert post.revision == "not a number"  # pyright: ignore[reportUnnecessaryComparison]
    assert post.schedule.publish_at is None


def nohead_warning() -> type[Warning]:
    from nohead import NoheadWarning

    return NoheadWarning
