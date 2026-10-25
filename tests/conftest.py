from __future__ import annotations

import asyncio
import inspect
import json
import time
import weakref
from collections.abc import Callable, Iterator
from typing import Any

import httpx
import pytest

from nohead import AsyncNohead, Nohead, _base

from .spec import check_reply, check_request, example_of

Reply = httpx.Response | Exception | Callable[[httpx.Request], httpx.Response]

API_HOST = "api.test"

_raw: weakref.WeakSet[httpx.Response] = weakref.WeakSet()


def raw(response: httpx.Response) -> httpx.Response:
    """A reply the contract check leaves alone: one that breaks the contract on purpose
    (a gateway's error page, a newer or older API)."""
    _raw.add(response)
    return response


class Recorder:
    """An httpx transport handler that answers from `replies` in order (the last one
    repeats) and records every request. Every request to the API, and every reply to it
    not marked raw(), must match the contract (tests/spec.py), or the test fails."""

    def __init__(self, replies: list[Reply]) -> None:
        self.replies = replies
        self.calls: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        request.read()
        self.calls.append(request)
        route = check_request(request) if request.url.host == API_HOST else None
        reply = self.replies[min(len(self.calls) - 1, len(self.replies) - 1)]
        if isinstance(reply, Exception):
            raise reply
        response = reply(request) if callable(reply) else reply
        if route is not None and response not in _raw:
            check_reply(route, response)
        # A fresh copy: a response object can be sent only once.
        return httpx.Response(
            response.status_code, headers=response.headers, content=response.content
        )

    def body(self, index: int) -> Any:
        return json.loads(self.calls[index].content)


def make_sync(replies: list[Reply], **options: Any) -> tuple[Nohead, Recorder]:
    recorder = Recorder(replies)
    client = httpx.Client(transport=httpx.MockTransport(recorder))
    defaults: dict[str, Any] = {
        "api_key": "nohead_sk_test",
        "base_url": f"https://{API_HOST}",
        "project_id": "prj_1",
    }
    return Nohead(http_client=client, **{**defaults, **options}), recorder


def make_async(replies: list[Reply], **options: Any) -> tuple[AsyncNohead, Recorder]:
    recorder = Recorder(replies)
    client = httpx.AsyncClient(transport=httpx.MockTransport(recorder))
    defaults: dict[str, Any] = {
        "api_key": "nohead_sk_test",
        "base_url": f"https://{API_HOST}",
        "project_id": "prj_1",
    }
    return AsyncNohead(http_client=client, **{**defaults, **options}), recorder


def json_response(status: int, body: Any, headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(status, json=body, headers=headers or {})


def api_error(
    status: int, type: str, headers: dict[str, str] | None = None, **extra: Any
) -> httpx.Response:
    error = {"type": type, "message": f"{type} message", "request_id": "req_1", **extra}
    return json_response(status, {"error": error}, headers)


def record(id: str, **data: Any) -> dict[str, Any]:
    """An unpublished record of `posts`, from the contract's example."""
    return example_of(
        "Record",
        id=id,
        collection_id="col_1",
        collection="posts",
        published_at=None,
        history_pruned_through=None,
        deleted_at=None,
        purge_after=None,
        data=data,
        expanded={},
        created_at="2026-10-02T12:00:00.000Z",
        updated_at="2026-10-02T12:00:00.000Z",
    )


def page(
    items: list[Any], next_cursor: str | None = None, *, has_more: bool, **meta: Any
) -> httpx.Response:
    body = {"data": items, "meta": {"next_cursor": next_cursor, "has_more": has_more, **meta}}
    return json_response(200, body)


LAST_PAGE = page([], has_more=False)
"""An empty list."""


Make = Callable[..., tuple[Any, Recorder]]


@pytest.fixture(params=["sync", "async"])
def make(request: pytest.FixtureRequest) -> Make:
    """make_sync or make_async: the test runs with each client. Await what the client's
    methods return with `resolve`."""
    return make_sync if request.param == "sync" else make_async


async def resolve(result: Any) -> Any:
    """What a call returns, awaited when the client is async."""
    return await result if inspect.isawaitable(result) else result


async def items(pages: Any, limit: int | None = None) -> list[Any]:
    """The items a list method's result walks, across pages (`for` or `async for`),
    stopping after `limit` items."""
    found: list[Any] = []
    if hasattr(pages, "__aiter__"):
        async for item in pages:
            found.append(item)
            if len(found) == limit:
                break
    else:
        for item in pages:
            found.append(item)
            if len(found) == limit:
                break
    return found


@pytest.fixture
def waits(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """The seconds each client waits between attempts, which take no time here."""
    found: list[float] = []

    async def sleep(seconds: float) -> None:
        found.append(seconds)

    monkeypatch.setattr(time, "sleep", found.append)
    monkeypatch.setattr(asyncio, "sleep", sleep)
    return found


BACKOFF = _base.backoff
"""The client's backoff, which no_backoff replaces in every test."""


@pytest.fixture(autouse=True)
def no_backoff(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Retries wait no time in tests, and each test warns afresh."""
    monkeypatch.setattr(_base, "backoff", lambda attempt: 0.0)  # pyright: ignore[reportUnknownLambdaType]
    monkeypatch.setattr(_base, "_warned_shapes", set[str]())
    monkeypatch.setattr(_base, "_warned_deprecations", set[str]())
    monkeypatch.setattr(_base, "_warned_usage", False)
    yield
