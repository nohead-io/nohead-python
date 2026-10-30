from __future__ import annotations

import asyncio
import dataclasses
import platform
import time
import tomllib
from concurrent.futures import ThreadPoolExecutor
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

import httpx
import pytest

from nohead import AsyncNohead, Nohead, NoheadError, __version__

from .conftest import LAST_PAGE, Make, json_response, make_sync, raw, record, resolve


def test_needs_an_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NOHEAD_API_KEY", "")
    with pytest.raises(NoheadError):
        Nohead()


def test_reads_the_key_from_the_environment_but_not_the_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NOHEAD_API_KEY", "nohead_sk_env")
    monkeypatch.setenv("NOHEAD_API_URL", "https://env.test/")
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return json_response(200, record("rec_1"))

    client = Nohead(http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    client.records.get("rec_1")
    assert str(seen[0].url) == "https://api.nohead.io/v1/records/rec_1"
    assert seen[0].headers["authorization"] == "Bearer nohead_sk_env"
    assert AsyncNohead()._client.settings.base_url == "https://api.nohead.io"


def test_takes_the_base_url_from_its_option(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NOHEAD_API_URL", "https://env.test")
    for client in (Nohead, AsyncNohead):
        assert client(api_key="k", base_url="https://api.test")._client.settings.base_url == (
            "https://api.test"
        )


def test_defaults_to_production() -> None:
    assert Nohead(api_key="nohead_sk_x")._client.settings.base_url == "https://api.nohead.io"


def test_identifies_itself() -> None:
    nohead, calls = make_sync([json_response(200, record("rec_1"))], headers={"X-Extra": "yes"})
    nohead.records.get("rec_1")
    headers = calls.calls[0].headers
    assert headers["nohead-client"] == f"sdk-python/{__version__}"
    assert (
        headers["user-agent"] == f"nohead-python/{__version__} python/{platform.python_version()}"
    )
    assert headers["accept"] == "application/json"
    assert headers["x-extra"] == "yes"


def test_version_matches_pyproject() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text())
    assert __version__ == pyproject["project"]["version"]


ME = json_response(
    200,
    {
        "object": "principal",
        "type": "api_key",
        "user": None,
        "api_key": {
            "id": "key_1",
            "name": "CI",
            "scopes": [],
            "published_only": False,
            "project_id": "prj_9",
            "expires_at": None,
        },
    },
)


async def test_looks_up_the_project_once(make: Make) -> None:
    nohead, calls = make([ME, LAST_PAGE], project_id=None)
    await resolve(nohead.collections.list())
    await resolve(nohead.assets.list())
    assert [c.url.path for c in calls.calls] == [
        "/v1/me",
        "/v1/projects/prj_9/collections",
        "/v1/projects/prj_9/assets",
    ]


def test_without_a_project_key() -> None:
    me = json_response(200, {"object": "principal", "type": "user", "user": None, "api_key": None})
    nohead, _ = make_sync([me], project_id=None)
    with pytest.raises(NoheadError, match="not a project API key"):
        nohead.collections.list()


def test_with_options_shares_the_connection() -> None:
    nohead, calls = make_sync([json_response(200, record("rec_1"))])
    faster = nohead.with_options(timeout=5, headers={"X-Job": "import"})
    faster.records.get("rec_1")
    assert faster._client.http is nohead._client.http
    assert faster._client.settings == dataclasses.replace(
        nohead._client.settings, timeout=5, headers={"X-Job": "import"}
    )
    assert calls.calls[0].headers["x-job"] == "import"


@pytest.mark.parametrize("client", [Nohead, AsyncNohead])
async def test_closes_its_connections_on_leaving_its_context(client: type[Any]) -> None:
    async with AsyncExitStack() as stack:
        nohead = client(api_key="nohead_sk_x")
        if isinstance(nohead, AsyncNohead):
            await stack.enter_async_context(nohead)
        else:
            stack.enter_context(nohead)
        assert not nohead._client.http.is_closed
    assert nohead._client.http.is_closed


async def test_leaves_a_given_http_client_open(make: Make) -> None:
    nohead, _ = make([])
    await resolve(nohead.close())
    assert not nohead._client.http.is_closed


def test_empty_options_count_as_not_given(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NOHEAD_API_KEY", "nohead_sk_env")
    nohead, calls = make_sync([ME, LAST_PAGE], api_key="", base_url="", project_id="")
    nohead.collections.list()
    assert [str(c.url) for c in calls.calls] == [
        "https://api.nohead.io/v1/me",
        "https://api.nohead.io/v1/projects/prj_9/collections",
    ]
    assert calls.calls[0].headers["authorization"] == "Bearer nohead_sk_env"


def test_removes_every_trailing_slash_of_the_base_url() -> None:
    assert Nohead(api_key="k", base_url="http://localhost:3000///")._client.settings.base_url == (
        "http://localhost:3000"
    )


@pytest.mark.parametrize(
    "base_url",
    ["ftp://api.test", "api.nohead.io", "localhost:3000", "http://", "https:///v1", "http://[::1"],
)
def test_refuses_a_base_url_that_is_not_http(base_url: str) -> None:
    for client in (Nohead, AsyncNohead):
        with pytest.raises(NoheadError, match=r"^base_url must be an http or https URL$"):
            client(api_key="k", base_url=base_url)


def fresh(response: httpx.Response) -> httpx.Response:
    """A copy of a reply to send: a response object can be sent only once."""
    return httpx.Response(response.status_code, headers=response.headers, content=response.content)


async def test_calls_at_the_same_time_share_one_project_lookup() -> None:
    seen: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        await asyncio.sleep(0.01)  # the others start meanwhile
        return fresh(ME if request.url.path == "/v1/me" else LAST_PAGE)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    nohead = AsyncNohead(api_key="k", base_url="https://api.test", http_client=http)
    copy = nohead.with_options(timeout=5)
    await asyncio.gather(nohead.collections.list(), nohead.webhooks.list(), copy.collections.list())
    assert seen.count("/v1/me") == 1
    await copy.collections.list()
    assert seen.count("/v1/me") == 1


def test_threads_share_one_project_lookup() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        time.sleep(0.05)  # the others start meanwhile
        return fresh(ME if request.url.path == "/v1/me" else LAST_PAGE)

    http = httpx.Client(transport=httpx.MockTransport(handler))
    nohead = Nohead(api_key="k", base_url="https://api.test", http_client=http)
    copy = nohead.with_options(timeout=5)
    with ThreadPoolExecutor(3) as pool:
        for future in [
            pool.submit(nohead.collections.list),
            pool.submit(nohead.webhooks.list),
            pool.submit(copy.collections.list),
        ]:
            future.result()
    assert seen.count("/v1/me") == 1


async def test_looks_up_the_project_again_after_a_failure(make: Make) -> None:
    nohead, calls = make(
        [raw(json_response(500, {})), ME, LAST_PAGE], project_id=None, max_retries=0
    )
    with pytest.raises(NoheadError):
        await resolve(nohead.collections.list())
    await resolve(nohead.collections.list())
    assert [c.url.path for c in calls.calls] == [
        "/v1/me",
        "/v1/me",
        "/v1/projects/prj_9/collections",
    ]


async def test_calls_at_the_same_time_share_a_failed_lookup() -> None:
    seen: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        await asyncio.sleep(0.01)
        return httpx.Response(401, json={"error": {"type": "authentication_error"}})

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    nohead = AsyncNohead(api_key="k", base_url="https://api.test", http_client=http)
    results = await asyncio.gather(
        nohead.collections.list(), nohead.webhooks.list(), return_exceptions=True
    )
    assert [type(result).__name__ for result in results] == ["AuthenticationError"] * 2
    assert seen == ["/v1/me"]
