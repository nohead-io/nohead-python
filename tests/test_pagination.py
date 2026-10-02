from __future__ import annotations

import pytest

from nohead import AsyncPage, NoheadError, Page

from .conftest import json_response, make_async, make_sync, page, record


def test_returns_the_first_page() -> None:
    nohead, calls = make_sync([page([record("rec_1")], "c2")])
    first = nohead.records.list("posts", limit=1)
    assert isinstance(first, Page)
    assert [r.id for r in first.data] == ["rec_1"]
    assert first.meta.next_cursor == "c2"
    assert first.has_next_page()
    assert "cursor" not in calls.calls[0].url.params


def test_iterates_across_pages_keeping_the_parameters() -> None:
    nohead, calls = make_sync(
        [page([record("rec_1"), record("rec_2")], "c2"), page([record("rec_3")], None)]
    )
    ids = [r.id for r in nohead.records.list("posts", filter={"status": "draft"})]
    assert ids == ["rec_1", "rec_2", "rec_3"]
    assert calls.calls[1].url.params["cursor"] == "c2"
    assert calls.calls[1].url.params["filter[status]"] == "draft"


def test_pages_by_hand() -> None:
    nohead, _ = make_sync([page([record("rec_1")], "c2"), page([record("rec_2")], None)])
    second = nohead.records.list("posts").get_next_page()
    assert second.data[0].id == "rec_2"
    assert not second.has_next_page()
    with pytest.raises(NoheadError):
        second.get_next_page()


def test_resumes_from_a_cursor() -> None:
    nohead, calls = make_sync([page([], None)])
    nohead.records.list("posts", cursor="saved")
    assert calls.calls[0].url.params["cursor"] == "saved"


def test_search_totals() -> None:
    body = {
        "data": [record("r")],
        "meta": {"next_cursor": None, "has_more": False, "total_estimate": 1},
    }
    nohead, calls = make_sync([json_response(200, body)])
    hits = nohead.search("hello", collections=["posts", "pages"])
    assert hits.meta.total_estimate == 1
    assert calls.calls[0].url.path == "/v1/projects/prj_1/search"
    assert calls.calls[0].url.params["collections"] == "posts,pages"


async def test_async_await_gives_the_first_page() -> None:
    nohead, _ = make_async([page([record("rec_1")], "c2")])
    first = await nohead.records.list("posts")
    assert isinstance(first, AsyncPage)
    assert first.data[0].id == "rec_1"


async def test_async_iterates_across_pages() -> None:
    nohead, calls = make_async([page([record("rec_1")], "c2"), page([record("rec_2")], None)])
    ids = [r.id async for r in nohead.records.list("posts")]
    assert ids == ["rec_1", "rec_2"]
    assert len(calls.calls) == 2


async def test_async_pages_by_hand() -> None:
    nohead, _ = make_async([page([record("rec_1")], "c2"), page([record("rec_2")], None)])
    first = await nohead.records.list("posts")
    second = await first.get_next_page()
    assert second.data[0].id == "rec_2"
