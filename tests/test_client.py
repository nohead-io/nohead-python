from __future__ import annotations

import platform
import tomllib
from pathlib import Path

import httpx
import pytest

from nohead import AsyncNohead, Nohead, NoheadError, __version__

from .conftest import json_response, make_async, make_sync, page, record


def test_needs_an_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NOHEAD_API_KEY", "")
    with pytest.raises(NoheadError):
        Nohead()


def test_reads_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NOHEAD_API_KEY", "sk_live_env")
    monkeypatch.setenv("NOHEAD_API_URL", "https://env.test/")
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return json_response(200, record("rec_1"))

    client = Nohead(http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    client.records.get("rec_1")
    assert str(seen[0].url) == "https://env.test/v1/records/rec_1"
    assert seen[0].headers["authorization"] == "Bearer sk_live_env"


def test_defaults_to_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NOHEAD_API_URL", "")
    assert Nohead(api_key="sk_live_x")._client.settings.base_url == "https://api.nohead.io"


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


def test_looks_up_the_project_once() -> None:
    nohead, calls = make_sync([ME, page([], None)], project_id=None)
    nohead.collections.list()
    nohead.webhooks.list()
    assert [c.url.path for c in calls.calls] == [
        "/v1/me",
        "/v1/projects/prj_9/collections",
        "/v1/projects/prj_9/webhooks",
    ]


async def test_async_looks_up_the_project_once() -> None:
    nohead, calls = make_async([ME, page([], None)], project_id=None)
    await nohead.collections.list()
    await nohead.assets.list()
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
    assert faster._client.settings.timeout == 5
    assert calls.calls[0].headers["x-job"] == "import"


def test_context_managers() -> None:
    with Nohead(api_key="sk_live_x") as nohead:
        assert not nohead._client.http.is_closed
    assert nohead._client.http.is_closed


async def test_async_context_manager() -> None:
    async with AsyncNohead(api_key="sk_live_x") as nohead:
        assert not nohead._client.http.is_closed
    assert nohead._client.http.is_closed
