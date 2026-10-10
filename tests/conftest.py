from __future__ import annotations

import asyncio
import inspect
import json
import time
from collections.abc import Callable, Iterator
from typing import Any

import httpx
import pytest

from nohead import AsyncNohead, Nohead, _base

Reply = httpx.Response | Exception | Callable[[httpx.Request], httpx.Response]


class Recorder:
    """An httpx transport handler that answers from `replies` in order (the last one
    repeats) and records every request."""

    def __init__(self, replies: list[Reply]) -> None:
        self.replies = replies
        self.calls: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        request.read()
        self.calls.append(request)
        reply = self.replies[min(len(self.calls) - 1, len(self.replies) - 1)]
        if isinstance(reply, Exception):
            raise reply
        response = reply(request) if callable(reply) else reply
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
        "api_key": "sk_live_test",
        "base_url": "https://api.test",
        "project_id": "prj_1",
    }
    return Nohead(http_client=client, **{**defaults, **options}), recorder


def make_async(replies: list[Reply], **options: Any) -> tuple[AsyncNohead, Recorder]:
    recorder = Recorder(replies)
    client = httpx.AsyncClient(transport=httpx.MockTransport(recorder))
    defaults: dict[str, Any] = {
        "api_key": "sk_live_test",
        "base_url": "https://api.test",
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
    return {
        "id": id,
        "object": "record",
        "collection_id": "col_1",
        "collection": "posts",
        "status": "draft",
        "published_at": None,
        "schedule": {"publish_at": None, "unpublish_at": None, "last_error": None},
        "revision": 1,
        "schema_version": 1,
        "history_pruned_through": None,
        "deleted": False,
        "data": data,
        "created_at": "2026-10-02T12:00:00.000Z",
        "updated_at": "2026-10-02T12:00:00.000Z",
    }


def page(items: list[Any], next_cursor: str | None, **meta: Any) -> httpx.Response:
    body = {
        "data": items,
        "meta": {"next_cursor": next_cursor, "has_more": next_cursor is not None, **meta},
    }
    return json_response(200, body)


Make = Callable[..., tuple[Any, Recorder]]


@pytest.fixture(params=["sync", "async"])
def make(request: pytest.FixtureRequest) -> Make:
    """make_sync or make_async: the test runs with each client. Await what the client's
    methods return with `resolve`."""
    return make_sync if request.param == "sync" else make_async


async def resolve(result: Any) -> Any:
    """What a call returns, awaited when the client is async."""
    return await result if inspect.isawaitable(result) else result


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
    """Retries wait no time in tests."""
    monkeypatch.setattr(_base, "backoff", lambda attempt: 0.0)  # pyright: ignore[reportUnknownLambdaType]
    monkeypatch.setattr(_base, "_warned_shapes", set[str]())
    yield
