"""Every API-key operation in the contract must be reachable from the SDK's public
methods, every request must match its operation (method, path, declared query parameters
and their values, and the JSON body), and every declared query parameter must be sent by
some call. A new operation or query parameter in openapi.json fails this test until a
method takes it (and a call in tests/calls.py or below passes it). Each call gets the
contract's examples of its operation's response, one for each variant of its unions
(`oneOf`, `anyOf`), and must return them, parsed without a NoheadWarning. A method
takes `if_match` and `change_note` exactly when its operation declares `If-Match` and
`Nohead-Change-Note`, and `rich_text` when it declares that query parameter; no request
sends a header its operation doesn't declare. Both clients are checked."""

from __future__ import annotations

import inspect
import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from pydantic import BaseModel

from nohead import AsyncNohead, AsyncPage, Nohead, NoheadWarning, Page
from nohead._generated.operations import OPERATIONS

from .calls import every_call, example_reply, mock_reply
from .conftest import Make, Recorder, api_error, json_response, make_sync, raw, record, resolve
from .spec import ROUTES, VARIANTS, declared_headers, errors, route_of_request

TIMESTAMP = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?(Z|[+-]\d\d:\d\d)")


def comparable(value: Any) -> Any:
    """A result or reply as JSON, with timestamps as datetimes: their formats differ."""
    if isinstance(value, Page | AsyncPage):
        return {"data": comparable(value.data), "meta": comparable(value.meta)}
    if isinstance(value, BaseModel):
        return comparable(value.model_dump(mode="json", by_alias=True, exclude_unset=True))
    if isinstance(value, dict):
        return {key: comparable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [comparable(item) for item in value]
    if isinstance(value, str) and TIMESTAMP.fullmatch(value):
        return datetime.fromisoformat(value)
    return value


# Query parameters an API key has no use for: it always acts on its own project.
NOT_FOR_API_KEYS = {"feature_flags_list": {"organization_id", "project_id"}}


def every_parameter(nohead: Any) -> list[Callable[[], Any]]:
    """Calls that pass the query parameters the samples in tests/calls.py leave out."""
    return [
        lambda: nohead.records.list("posts", cursor="cur_x"),
        lambda: nohead.records.revisions.list(
            "rec_01J9ZQ3F8X",
            filter={"created_at": {"gte": datetime(2026, 10, 1, tzinfo=UTC)}},
            limit=5,
            cursor="cur_x",
        ),
        lambda: nohead.records.search("posts", "hello", limit=5, cursor="cur_x"),
        lambda: nohead.search("hello", limit=5, cursor="cur_x"),
        lambda: nohead.collections.list(limit=5, cursor="cur_x"),
        lambda: nohead.records.scheduled_changes("posts", limit=5, cursor="cur_x"),
        lambda: nohead.records.drafts("rec_01J9ZQ3F8X", limit=5, cursor="cur_x"),
        lambda: nohead.drafts.list("posts", sort="updated_at", limit=5, cursor="cur_x"),
        lambda: nohead.collections.schema_changes.list("posts", limit=5, cursor="cur_x"),
        lambda: nohead.fields.list("posts", limit=5, cursor="cur_x"),
        lambda: nohead.migrations.list("posts", limit=5, cursor="cur_x"),
        lambda: nohead.assets.list(content_type="image/*", limit=5, cursor="cur_x"),
        lambda: nohead.assets.list(content_type=["image/*", "application/pdf"]),
        lambda: nohead.assets.list(q="hero jpg", kind="image"),
        lambda: nohead.assets.list(kind=["image", "video"]),
        lambda: nohead.webhooks.list(limit=5, cursor="cur_x"),
        lambda: nohead.webhooks.deliveries.list("wh_01J9ZQ3F8X", limit=5, cursor="cur_x"),
        lambda: nohead.webhooks.secrets.list("wh_01J9ZQ3F8X", limit=5, cursor="cur_x"),
        lambda: nohead.audit_events.list(
            filter={
                "resource_type": ["collection", "field"],
                "resource_id": "col_01J9ZQ3F8X",
                "actor_type": "api_key",
                "actor_id": "key_01J9ZQ3F8X",
                "created_at": {"gte": "2026-10-01T00:00:00Z", "lt": "2026-11-01T00:00:00Z"},
            },
            limit=5,
            cursor="cur_x",
        ),
        lambda: nohead.audit_events.list(filter={"resource_type": "record"}),
        lambda: nohead.records.list("posts", rich_text="html"),
        lambda: nohead.records.get("rec_01J9ZQ3F8X", rich_text="markdown"),
        lambda: nohead.records.create("posts", data={"body": "# Hi"}, rich_text="markdown"),
        lambda: nohead.records.update("rec_01J9ZQ3F8X", data={}, rich_text="html"),
        lambda: nohead.records.delete("rec_01J9ZQ3F8X", rich_text="html"),
        lambda: nohead.records.restore("rec_01J9ZQ3F8X", rich_text="html"),
        lambda: nohead.records.publish("rec_01J9ZQ3F8X", rich_text="html"),
        lambda: nohead.records.unpublish("rec_01J9ZQ3F8X", rich_text="html"),
        lambda: nohead.records.drafts("rec_01J9ZQ3F8X", rich_text="html"),
        lambda: nohead.records.bulk(
            "posts", action="publish", record_ids=["rec_01J9ZQ3F8X"], rich_text="html"
        ),
        lambda: nohead.records.search("posts", "hello", rich_text="html"),
        lambda: nohead.records.revisions.revert("rec_01J9ZQ3F8X", 1, rich_text="document"),
        lambda: nohead.search("hello", rich_text="html"),
        lambda: nohead.drafts.create("rec_01J9ZQ3F8X", rich_text="html"),
        lambda: nohead.drafts.list("posts", rich_text="html"),
        lambda: nohead.drafts.get("drf_01J9ZQ3F8X", rich_text="html"),
        lambda: nohead.drafts.update("drf_01J9ZQ3F8X", data={}, rich_text="html"),
        lambda: nohead.drafts.merge("drf_01J9ZQ3F8X", rich_text="html"),
        lambda: nohead.drafts.schedule(
            "drf_01J9ZQ3F8X", merge_at="2027-01-01T09:00:00Z", rich_text="html"
        ),
        lambda: nohead.drafts.unschedule("drf_01J9ZQ3F8X", rich_text="html"),
        lambda: nohead.drafts.discard("drf_01J9ZQ3F8X", rich_text="html"),
    ]


def check_requests(requests: list[httpx.Request], sent: dict[str, set[str]]) -> None:
    """Notes the query parameters one call's requests sent. (The mock transport checks
    each request against its operation: tests/spec.py, check_request.)"""
    for request in requests:
        route = route_of_request(request)
        sent.setdefault(route.id, set()).update(k.split("[", 1)[0] for k in request.url.params)


def check_result(requests: list[httpx.Request], result: Any, variant: int) -> None:
    """The method returns the response its last request got."""
    last = requests[-1]
    route = route_of_request(last)
    reply = example_reply(route, last, variant)
    assert comparable(result) == comparable(reply), f"{route.id}, variant {variant}"


def check_coverage(sent: dict[str, set[str]]) -> None:
    assert sorted(set(OPERATIONS) - set(sent)) == [], "operations without an SDK method"
    unsent = {
        route.id: sorted(
            {p.name for p in route.query} - sent[route.id] - NOT_FOR_API_KEYS.get(route.id, set())
        )
        for route in ROUTES
    }
    assert {op: p for op, p in unsent.items() if p} == {}, "query parameters no call sends"


def api_requests(recorder: Recorder, start: int) -> list[httpx.Request]:
    return [r for r in recorder.calls[start:] if r.url.host == "api.test"]


def replies_of(requests: list[httpx.Request], variant: int) -> list[Any]:
    """The replies a call's API requests get with the variant numbered `variant`."""
    return [example_reply(route_of_request(r), r, variant) for r in requests]


async def test_both_clients_cover_the_contract(make: Make) -> None:
    """Each call runs with every variant of its replies' unions. A variant is skipped
    when it gives the requests of a run already made the same replies: the client then
    sends the same requests again, and gets the same results."""
    variant = [0]  # the variant the mock answers with, set below
    nohead, recorder = make([lambda request: mock_reply(request, variant[0])])
    sent: dict[str, set[str]] = {}
    for call in every_call(nohead) + every_parameter(nohead):
        runs: list[tuple[list[httpx.Request], list[Any]]] = []
        for number in range(VARIANTS):
            if any(replies_of(requests, number) == replies for requests, replies in runs):
                continue
            variant[0] = number
            start = len(recorder.calls)
            result = await resolve(call())
            requests = api_requests(recorder, start)
            runs.append((requests, replies_of(requests, number)))
            check_requests(requests, sent)
            check_result(requests, result, number)
    check_coverage(sent)


async def test_the_clients_rich_text_goes_where_it_is_declared(make: Make) -> None:
    """The client's `rich_text` is sent with exactly the operations that declare it."""
    nohead, recorder = make([mock_reply], rich_text="markdown")
    # records.diff's sample passes its own rich_text: here it takes the client's.
    calls = [
        *every_call(nohead),
        lambda: nohead.records.diff("rec_1", from_revision=1, to_revision=2),
    ]
    for call in calls:
        await resolve(call())
    declared = {route.id for route in ROUTES if any(p.name == "rich_text" for p in route.query)}
    sent: set[str] = set()
    for request in api_requests(recorder, 0):
        operation = route_of_request(request).id
        expected = "markdown" if operation in declared else None
        assert request.url.params.get("rich_text") == expected, operation
        sent.add(operation)
    assert declared <= sent, "operations that declare rich_text no call sends"


@pytest.mark.parametrize("variant", range(VARIANTS))
def test_every_success_response_has_valid_examples(variant: int) -> None:
    for route in ROUTES:
        request = httpx.Request(route.method, "https://api.test/")
        reply = example_reply(route, request, variant)
        assert errors(route.response.schema_at, reply) == [], route.id


def operations_of(method: Callable[..., Any]) -> set[str]:
    """The operations a method calls, by the IDs in its source."""
    source = inspect.getsource(method)
    return {op for op in re.findall(r'"(\w+)"', source) if op in OPERATIONS}


@pytest.mark.parametrize("client", [Nohead, AsyncNohead])
def test_methods_take_the_options_their_operations_declare(client: type[Any]) -> None:
    queries = {route.id: {p.name for p in route.query} for route in ROUTES}
    checked: set[str] = set()
    for name, method in public_methods(client(api_key="nohead_sk_x")).items():
        operations = operations_of(method)
        if len(operations) != 1:
            continue  # a helper, such as assets.upload or webhooks.unwrap
        (operation,) = operations
        declared = declared_headers(operation)
        parameters = inspect.signature(method).parameters
        assert ("if_match" in parameters) == ("if-match" in declared), f"{name} if_match"
        assert ("change_note" in parameters) == ("nohead-change-note" in declared), (
            f"{name} change_note"
        )
        assert ("idempotency_key" in parameters) == ("idempotency-key" in declared), (
            f"{name} idempotency_key"
        )
        assert ("rich_text" in parameters) == ("rich_text" in queries[operation]), (
            f"{name} rich_text"
        )
        checked.add(operation)
    assert sorted(set(OPERATIONS) - checked) == [], "operations no method was checked for"


def public_methods(obj: object, prefix: str = "") -> dict[str, Callable[..., Any]]:
    """The client's methods by name (`records.revisions.revert`), resources' too."""
    found: dict[str, Callable[..., Any]] = {}
    for name in dir(obj):
        if name.startswith("_") or name in {"with_options", "close"}:
            continue
        value = getattr(obj, name)
        if callable(value):
            found[prefix + name] = value
        elif hasattr(value, "_client"):
            found |= public_methods(value, f"{prefix}{name}.")
    return found


def test_both_clients_have_the_same_methods() -> None:
    sync = set(public_methods(Nohead(api_key="nohead_sk_x")))
    assert sync == set(public_methods(AsyncNohead(api_key="nohead_sk_x")))
    assert "records.revisions.revert" in sync


def test_the_mock_transport_checks_requests_and_replies() -> None:
    """Every test's requests and replies are checked against the contract (conftest.py)."""
    nohead, _ = make_sync([json_response(200, {"id": "rec_1"})])
    with pytest.raises(AssertionError, match="records_get 200 reply does not match"):
        nohead.records.get("rec_1")
    nohead, _ = make_sync([api_error(500, "internal_error", detail="extra")])
    with pytest.raises(AssertionError, match="records_get 500 reply does not match"):
        nohead.records.get("rec_1")
    nohead, _ = make_sync([json_response(200, record("rec_1"))])
    with pytest.raises(AssertionError, match="undeclared query parameters"):
        nohead._client.send("records_get", path={"record_id": "rec_1"}, query={"bogus": 1})
    # raw() lets a reply that breaks the contract on purpose through.
    nohead, _ = make_sync([raw(json_response(200, {"id": "rec_1"}))])
    with pytest.warns(NoheadWarning):
        assert nohead.records.get("rec_1").id == "rec_1"
