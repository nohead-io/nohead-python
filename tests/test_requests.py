from __future__ import annotations

import math
import re
import warnings
from datetime import UTC, date, datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

import pytest

from nohead import NoheadError, models
from nohead.models import RecordBatchResultsFailed, RecordBatchResultsSucceeded, TextField

from .conftest import LAST_PAGE, Make, json_response, make_sync, page, raw, record, resolve
from .spec import SPEC, example_of


def test_encodes_path_parameters() -> None:
    nohead, calls = make_sync([LAST_PAGE])
    nohead.records.list("my posts/1")
    assert calls.calls[0].url.raw_path.startswith(b"/v1/collections/my%20posts%2F1/records")


@pytest.mark.parametrize("value", ["", None])
def test_refuses_a_missing_path_parameter(value: str | None) -> None:
    nohead, calls = make_sync([LAST_PAGE])
    with pytest.raises(NoheadError, match="Missing record_id"):
        nohead.records.get(value)  # pyright: ignore[reportArgumentType]
    assert calls.calls == []


def test_serializes_filters_sorts_and_expansions() -> None:
    nohead, calls = make_sync([LAST_PAGE])
    nohead.records.list(
        "posts",
        filter={
            "category": "news",
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
    assert params["filter[category]"] == "news"
    assert params["filter[featured]"] == "true"
    assert params["filter[views]"] == "3"
    assert params["filter[published_after]"] == "2026-01-01T00:00:00Z"
    assert "filter[skip]" not in params
    assert params["sort"] == "-published_at"
    assert params["expand"] == "author,tags"
    assert params["limit"] == "50"
    assert "cursor" not in params


def test_serializes_filter_operators_escaping_commas_in_lists() -> None:
    nohead, calls = make_sync([LAST_PAGE])
    nohead.records.list(
        "products",
        filter={
            "brand": {"ne": "acme"},
            "price": {"gte": 10, "lt": 50},
            "category": {"in": ["shoes", "hats, caps", "a\\b"]},
            "cover": {"exists": True},
            "released": {"gte": date(2026, 10, 9)},
        },
        sort="-price",
    )
    params = calls.calls[0].url.params
    assert params["filter[brand][ne]"] == "acme"
    assert params["filter[price][gte]"] == "10"
    assert params["filter[price][lt]"] == "50"
    assert params["filter[category][in]"] == "shoes,hats\\, caps,a\\\\b"
    assert params["filter[cover][exists]"] == "true"
    assert params["filter[released][gte]"] == "2026-10-09"
    assert params["sort"] == "-price"


def test_leaves_missing_list_items_out_and_a_list_of_none() -> None:
    nohead, calls = make_sync([LAST_PAGE])
    nohead.records.list(
        "products",
        filter={"category": {"in": ["shoes", None]}, "tag": {"in": [None]}, "size": {"in": []}},
        expand=[],
    )
    assert dict(calls.calls[0].url.params) == {"filter[category][in]": "shoes"}


async def test_sends_bodies_as_json(make: Make) -> None:
    nohead, calls = make([json_response(201, record("rec_1"))])
    created = await resolve(
        nohead.records.create("posts", data={"title": "Hi"}, change_note="Import")
    )
    assert created.id == "rec_1"
    assert calls.calls[0].method == "POST"
    assert calls.calls[0].headers["content-type"] == "application/json"
    assert calls.calls[0].headers["nohead-change-note"] == "Import"
    assert calls.body(0) == {"data": {"title": "Hi"}}


SCHEDULE = {
    "object": "schedule",
    "record_id": "rec_1",
    "publish_at": None,
    "unpublish_at": None,
    "last_error": None,
}


def test_serializes_dates_in_bodies() -> None:
    nohead, calls = make_sync([json_response(200, SCHEDULE)])
    nohead.records.schedule("rec_1", publish_at=datetime(2027, 1, 1, 9, tzinfo=UTC))
    assert calls.body(0) == {"publish_at": "2027-01-01T09:00:00Z"}


def test_sets_the_whole_schedule() -> None:
    nohead, calls = make_sync([json_response(200, SCHEDULE)])
    nohead.records.schedule("rec_1", unpublish_at="2027-02-01T00:00:00Z")
    nohead.records.schedule("rec_1")
    # A time left out is cleared, so only the given ones are sent.
    assert calls.body(0) == {"unpublish_at": "2027-02-01T00:00:00Z"}
    assert calls.body(1) == {}


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
    nohead.records.restore("rec_1", if_match=4)
    assert [c.headers["if-match"] for c in calls.calls] == ['"3"', '"1"', '"4"']


def test_search_filters_and_collections() -> None:
    nohead, calls = make_sync([page([], has_more=False, total_estimate=0)])
    nohead.search("hi", collections=["posts", "pages"], filter={"published_at": {"exists": True}})
    params = calls.calls[0].url.params
    assert params["filter[collection][in]"] == "posts,pages"
    assert params["filter[published_at][exists]"] == "true"


def test_audit_events_filter_several_resource_types_and_a_time_range() -> None:
    nohead, calls = make_sync([LAST_PAGE])
    nohead.audit_events.list(
        filter={
            "type": "field.*",
            "resource_type": ["collection", "field"],
            "created_at": {"gte": datetime(2026, 10, 1, tzinfo=UTC)},
        }
    )
    nohead.audit_events.list(filter={"resource_type": "record"})
    assert dict(calls.calls[0].url.params) == {
        "filter[type]": "field.*",
        "filter[resource_type][in]": "collection,field",
        "filter[created_at][gte]": "2026-10-01T00:00:00Z",
    }
    assert dict(calls.calls[1].url.params) == {"filter[resource_type]": "record"}


def test_lists_assets_of_one_type_or_several() -> None:
    nohead, calls = make_sync([LAST_PAGE, LAST_PAGE])
    nohead.assets.list(content_type="image/*").data  # noqa: B018 (fetches it)
    nohead.assets.list(content_type=["image/*", "application/pdf"]).data  # noqa: B018
    assert dict(calls.calls[0].url.params) == {"filter[content_type]": "image/*"}
    assert dict(calls.calls[1].url.params) == {
        "filter[content_type][in]": "image/*,application/pdf"
    }


def test_searches_assets_and_lists_them_by_kind() -> None:
    nohead, calls = make_sync([LAST_PAGE, LAST_PAGE])
    nohead.assets.list(q="hero jpg", kind="image").data  # noqa: B018 (fetches it)
    nohead.assets.list(kind=["image", "video"]).data  # noqa: B018
    assert dict(calls.calls[0].url.params) == {"q": "hero jpg", "filter[kind]": "image"}
    assert dict(calls.calls[1].url.params) == {"filter[kind][in]": "image,video"}


def test_record_batch_results_that_failed() -> None:
    batch = {
        "object": "record_batch",
        "action": "publish",
        "succeeded": 1,
        "failed": 1,
        "results": [
            {"id": "rec_1", "status": "succeeded", "changed": True, "record": record("rec_1")},
            {
                "id": "rec_2",
                "status": "failed",
                "error": {"type": "not_found", "message": "Record not found"},
            },
        ],
    }
    nohead, _ = make_sync([json_response(200, batch)])
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        result = nohead.records.bulk("posts", action="publish", record_ids=["rec_1", "rec_2"])
    succeeded, failed = result.results
    assert isinstance(succeeded, RecordBatchResultsSucceeded)
    assert succeeded.record.id == "rec_1"
    assert isinstance(failed, RecordBatchResultsFailed)
    assert (failed.id, failed.error.type) == ("rec_2", "not_found")


def test_record_batch_results_a_newer_api_changed() -> None:
    batch = {
        "object": "record_batch",
        "action": "publish",
        "succeeded": 0,
        "failed": 1,
        "results": [{"id": "rec_2", "status": "failed", "error": {"code": 7}}],
    }
    nohead, _ = make_sync([raw(json_response(200, batch))])
    with pytest.warns(nohead_warning()):
        result = nohead.records.bulk("posts", action="publish", record_ids=["rec_2"])
    # Unvalidated, it is still the variant it says it is.
    assert isinstance(result.results[0], RecordBatchResultsFailed)


def test_change_note_in_any_language_percent_encoded() -> None:
    nohead, calls = make_sync(
        [json_response(200, record("rec_1")), json_response(200, record("rec_1"))]
    )
    nohead.records.delete("rec_1", change_note="Duplicate")
    nohead.records.delete("rec_1", change_note="Rettet på forsiden ✓")
    assert calls.calls[0].headers["nohead-change-note"] == "Duplicate"
    assert calls.calls[1].headers["nohead-change-note"] == "Rettet%20p%C3%A5%20forsiden%20%E2%9C%93"
    nohead.records.delete("rec_1", change_note="Cut \ud83d")
    assert calls.calls[2].headers["nohead-change-note"] == "Cut%20%EF%BF%BD"


def test_dry_runs_are_query_parameters() -> None:
    preview = example_of("FieldMigrationPreview", field_id="fld_1")
    nohead, calls = make_sync([json_response(200, preview)])
    nohead.migrations.create("posts", field_id="fld_1", type="integer", dry_run=True)
    assert calls.calls[0].url.path == "/v1/collections/posts/migrations"
    assert calls.calls[0].url.params["dry_run"] == "true"
    assert calls.body(0) == {"field_id": "fld_1", "type": "integer"}


def test_diff_names_its_revisions() -> None:
    diff = {"object": "record_diff", "record_id": "rec_1", "from": 1, "to": 2, "changes": []}
    nohead, calls = make_sync([json_response(200, diff)])
    result = nohead.records.diff("rec_1", from_revision=1, to_revision=2)
    assert (result.from_, result.to) == (1, 2)
    assert dict(calls.calls[0].url.params) == {"from": "1", "to": "2"}


def test_keeps_unknown_fields_and_values() -> None:
    body = record("rec_1", title="Hi") | {"collection": "archive", "brand_new": True}
    nohead, _ = make_sync([raw(json_response(200, body))])
    post = nohead.records.get("rec_1")
    assert post.collection == "archive"
    assert post.model_extra == {"brand_new": True}
    assert post.created_at == datetime(2026, 10, 2, 12, tzinfo=UTC)


def test_builds_responses_that_do_not_match_the_models() -> None:
    odd = record("rec_1") | {"revision": "not a number", "published_at": "not a time"}
    nohead, _ = make_sync([raw(json_response(200, odd))])
    with pytest.warns(nohead_warning()):
        post = nohead.records.get("rec_1")
    assert post.id == "rec_1"
    assert post.revision == "not a number"  # pyright: ignore[reportUnnecessaryComparison]
    assert post.published_at == "not a time"  # pyright: ignore[reportUnnecessaryComparison]
    # The fields that do match keep their types.
    assert post.created_at == datetime(2026, 10, 2, 12, tzinfo=UTC)


def test_parses_what_it_can_of_a_response_missing_a_field() -> None:
    # An older API, without a field this SDK expects.
    body = {key: value for key, value in record("rec_1").items() if key != "revision"}
    nohead, _ = make_sync([raw(json_response(200, body))])
    with pytest.warns(nohead_warning()):
        post = nohead.records.get("rec_1")
    assert post.created_at == datetime(2026, 10, 2, 12, tzinfo=UTC)


FIELD_TYPES = SPEC["components"]["schemas"]["Field"]["discriminator"]["mapping"]


@pytest.mark.parametrize("kind", FIELD_TYPES)
def test_parses_every_field_type_as_its_model(kind: str) -> None:
    model = FIELD_TYPES[kind].rsplit("/", 1)[1]
    body = example_of(model)
    nohead, _ = make_sync([json_response(200, body), page([body], has_more=False)])
    field = nohead.fields.get("fld_1")
    listed = next(iter(nohead.fields.list("posts")))
    for parsed in (field, listed):
        assert type(parsed) is getattr(models, model)
        assert (parsed.type, parsed.id) == (kind, body["id"])


def test_a_field_that_does_not_match_counts_only_its_types_differences() -> None:
    # Field is a union discriminated by `type`: a text field is checked as a text
    # field only, not against every field type (43 differences, not 3).
    body = example_of("TextField")
    del body["name"], body["key"], body["configuration"]
    nohead, _ = make_sync([raw(json_response(200, body))])
    with pytest.warns(
        nohead_warning(), match=r"SDK's TextField model; returning it unvalidated \(3 differences\)"
    ):
        field = nohead.fields.get("fld_1")
    assert isinstance(field, TextField)
    assert (field.id, field.type) == (body["id"], "text")


def test_a_field_of_a_type_the_sdk_does_not_know_comes_unvalidated() -> None:
    body = example_of("TextField", type="geo", configuration={"precision": 6})
    nohead, _ = make_sync([raw(json_response(200, body))])
    with pytest.warns(nohead_warning(), match=r"\(1 differences\)"):
        field = nohead.fields.get("fld_1")
    # Built as the model it fits best, keeping what it says.
    assert isinstance(field, TextField)
    assert (field.id, field.type) == (body["id"], "geo")
    assert field.configuration.model_extra == {"precision": 6}
    assert field.created_at == datetime(2026, 9, 27, 12, tzinfo=UTC)


def nohead_warning() -> type[Warning]:
    from nohead import NoheadWarning

    return NoheadWarning


@pytest.mark.parametrize("value", [".", ".."])
def test_refuses_a_path_value_that_urls_resolve(value: str) -> None:
    # Encoded or not, `..` would request the parent: GET /v1/records/.. is /v1/.
    nohead, calls = make_sync([LAST_PAGE])
    with pytest.raises(NoheadError, match=f'^Invalid record_id: "{re.escape(value)}"$'):
        nohead.records.get(value)
    assert calls.calls == []


def test_sends_each_header_once_whatever_its_case() -> None:
    nohead, calls = make_sync(
        [json_response(201, record("rec_1"))],
        headers={
            "authorization": "Bearer nohead_sk_other",
            "accept": "application/json; charset=utf-8",
            "CONTENT-TYPE": "text/plain",
            "idempotency-key": "from-the-client",
            "x-extra": "yes",
        },
    )
    nohead.records.create("posts", data={}, idempotency_key="import-1", change_note="Import")
    headers = calls.calls[0].headers
    # The client's headers replace the defaults; the request's options win over both.
    assert headers.get_list("authorization") == ["Bearer nohead_sk_other"]
    assert headers.get_list("accept") == ["application/json; charset=utf-8"]
    assert headers.get_list("content-type") == ["application/json"]
    assert headers.get_list("idempotency-key") == ["import-1"]
    assert headers.get_list("x-extra") == ["yes"]


def test_with_options_replaces_a_header_whatever_its_case() -> None:
    nohead, calls = make_sync([json_response(200, record("rec_1"))], headers={"X-Job": "a"})
    nohead.with_options(headers={"x-job": "b"}).records.get("rec_1")
    assert calls.calls[0].headers.get_list("x-job") == ["b"]


def test_if_match_from_a_mapping_with_a_revision() -> None:
    nohead, calls = make_sync([json_response(200, record("rec_1"))])
    nohead.records.update("rec_1", data={}, if_match={"revision": 5})
    assert calls.calls[0].headers["if-match"] == '"5"'


@pytest.mark.parametrize("value", ["3", True, 3.0, None, {"rev": 3}, {"revision": "3"}, object()])
def test_if_match_refuses_anything_else(value: object) -> None:
    nohead, calls = make_sync([json_response(200, record("rec_1"))])
    if_match: Any = value if value is not None else SimpleNamespace(revision=None)
    with pytest.raises(TypeError, match="if_match takes a revision number"):
        nohead.records.publish("rec_1", if_match=if_match)
    assert calls.calls == []


def test_refuses_a_time_without_a_time_zone() -> None:
    nohead, calls = make_sync([json_response(200, SCHEDULE), LAST_PAGE])
    with pytest.raises(ValueError, match="has no time zone: pass an aware datetime"):
        nohead.records.schedule("rec_1", publish_at=datetime(2027, 1, 1, 9))
    with pytest.raises(ValueError, match="has no time zone"):
        nohead.records.list("posts", filter={"published_at": {"gte": datetime(2027, 1, 1)}})
    assert calls.calls == []


def test_sends_aware_times_in_utc() -> None:
    nohead, calls = make_sync([json_response(200, SCHEDULE)])
    plus_two = timezone(timedelta(hours=2))
    nohead.records.schedule("rec_1", publish_at=datetime(2027, 1, 1, 11, tzinfo=plus_two))
    assert calls.body(0) == {"publish_at": "2027-01-01T09:00:00Z"}


@pytest.mark.parametrize("number", [math.nan, math.inf, -math.inf])
def test_refuses_numbers_json_cannot_carry(number: float) -> None:
    nohead, calls = make_sync([json_response(201, record("rec_1"))])
    with pytest.raises(ValueError, match="not JSON compliant"):
        nohead.records.create("posts", data={"price": number})
    assert calls.calls == []


def test_empty_request_options_count_as_not_given() -> None:
    nohead, calls = make_sync([json_response(201, record("rec_1"))])
    nohead.records.create("posts", data={}, idempotency_key="", change_note="")
    headers = calls.calls[0].headers
    assert len(headers["idempotency-key"]) == 36
    assert "nohead-change-note" not in headers
