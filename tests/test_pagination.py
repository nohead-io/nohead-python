"""Pages of lists, with each client (the `make` fixture)."""

from __future__ import annotations

import httpx
import pytest

from nohead import AsyncPage, NoheadError, Page

from .conftest import LAST_PAGE, Make, items, json_response, page, raw, record, resolve


async def test_returns_the_first_page_then_pages_by_hand(make: Make) -> None:
    nohead, calls = make(
        [page([record("rec_1")], "c2", has_more=True), page([record("rec_2")], has_more=False)]
    )
    first = await resolve(nohead.records.list("posts", limit=1))
    assert isinstance(first, Page | AsyncPage)
    assert [r.id for r in first.data] == ["rec_1"]
    assert first.meta.next_cursor == "c2"
    assert first.has_next_page()
    assert "cursor" not in calls.calls[0].url.params
    second = await resolve(first.get_next_page())
    assert second.data[0].id == "rec_2"
    assert calls.calls[1].url.params["cursor"] == "c2"
    assert not second.has_next_page()
    with pytest.raises(NoheadError):
        await resolve(second.get_next_page())


async def test_iterates_across_pages_keeping_the_parameters(make: Make) -> None:
    nohead, calls = make(
        [
            page([record("rec_1"), record("rec_2")], "c2", has_more=True),
            page([record("rec_3")], has_more=False),
        ]
    )
    found = await items(nohead.records.list("posts", filter={"published_at": {"exists": False}}))
    assert [r.id for r in found] == ["rec_1", "rec_2", "rec_3"]
    assert calls.calls[1].url.params["cursor"] == "c2"
    assert calls.calls[1].url.params["filter[published_at][exists]"] == "false"


async def test_stops_fetching_once_it_has_enough(make: Make) -> None:
    nohead, calls = make([page([record("rec_1"), record("rec_2")], "c2", has_more=True)])
    assert [r.id for r in await items(nohead.records.list("posts"), limit=1)] == ["rec_1"]
    assert len(calls.calls) == 1


@pytest.mark.parametrize(
    ("next_cursor", "has_more"), [(None, True), ("c2", False)], ids=["no cursor", "no more"]
)
async def test_stops_unless_there_is_more_and_a_cursor(
    make: Make, next_cursor: str | None, has_more: bool
) -> None:
    stop = page([record("rec_1")], next_cursor, has_more=has_more)
    nohead, calls = make([stop, page([record("rec_2")], has_more=False)])
    first = await resolve(nohead.records.list("posts"))
    assert not first.has_next_page()
    assert [r.id for r in await items(first)] == ["rec_1"]
    assert len(calls.calls) == 1


async def test_walks_past_an_empty_page(make: Make) -> None:
    nohead, calls = make(
        [
            page([], "c2", has_more=True),
            page([record("rec_1")], "c3", has_more=True),
            page([], has_more=False),
        ]
    )
    assert [r.id for r in await items(nohead.records.list("posts"))] == ["rec_1"]
    assert [c.url.params.get("cursor") for c in calls.calls] == [None, "c2", "c3"]


async def test_resumes_from_a_cursor(make: Make) -> None:
    nohead, calls = make([LAST_PAGE])
    await resolve(nohead.records.list("posts", cursor="saved"))
    assert calls.calls[0].url.params["cursor"] == "saved"


async def test_search_totals(make: Make) -> None:
    body = {
        "data": [record("r")],
        "meta": {"next_cursor": None, "has_more": False, "total_estimate": 1},
    }
    nohead, calls = make([json_response(200, body)])
    hits = await resolve(nohead.search("hello", collections=["posts", "pages"]))
    assert hits.meta.total_estimate == 1
    assert calls.calls[0].url.path == "/v1/projects/prj_1/search"
    assert calls.calls[0].url.params["filter[collection][in]"] == "posts,pages"


@pytest.mark.parametrize(
    "reply",
    [
        httpx.Response(200, json=[record("rec_1")]),
        httpx.Response(200, text="OK"),
        httpx.Response(204),
        httpx.Response(200, json={"data": None, "meta": {"has_more": False}}),
        httpx.Response(200, json={"data": [], "meta": None}),
    ],
    ids=["array", "text", "empty", "data not a list", "meta not an object"],
)
async def test_a_list_response_it_cannot_read(make: Make, reply: httpx.Response) -> None:
    nohead, _ = make([raw(reply)])
    with pytest.raises(NoheadError, match=r"^The API's response could not be read \(HTTP 20\d\)$"):
        await items(await resolve(nohead.records.list("posts")))
