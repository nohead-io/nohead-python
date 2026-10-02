from __future__ import annotations

import httpx
import pytest

from nohead import APIConnectionError, APITimeoutError, RateLimitError, ValidationError

from .conftest import api_error, json_response, make_async, make_sync, record

NOW = {"retry-after": "0"}


def test_retries_server_errors_with_one_idempotency_key() -> None:
    nohead, calls = make_sync(
        [
            api_error(500, "internal_error", NOW),
            api_error(503, "service_unavailable", NOW),
            json_response(201, record("rec_1")),
        ]
    )
    assert nohead.records.create("posts", data={}).id == "rec_1"
    assert len(calls.calls) == 3
    assert len({c.headers["idempotency-key"] for c in calls.calls}) == 1


def test_waits_out_a_short_retry_after() -> None:
    nohead, calls = make_sync(
        [api_error(429, "rate_limited", NOW), json_response(200, record("r"))]
    )
    nohead.records.get("r")
    assert len(calls.calls) == 2


def test_gives_up_on_a_long_retry_after() -> None:
    nohead, calls = make_sync([api_error(429, "rate_limited", {"retry-after": "120"})])
    with pytest.raises(RateLimitError):
        nohead.records.get("r")
    assert len(calls.calls) == 1


def test_retries_a_request_in_progress() -> None:
    busy = api_error(409, "conflict", NOW, details=[{"code": "in_progress", "message": "..."}])
    nohead, calls = make_sync([busy, json_response(201, record("r"))])
    nohead.records.create("posts", data={})
    assert len(calls.calls) == 2


def test_does_not_retry_other_client_errors() -> None:
    nohead, calls = make_sync([api_error(422, "validation_error")])
    with pytest.raises(ValidationError):
        nohead.records.create("posts", data={})
    assert len(calls.calls) == 1


def test_retries_connection_failures() -> None:
    nohead, calls = make_sync([httpx.ConnectError("refused"), json_response(200, record("r"))])
    nohead.records.get("r")
    assert len(calls.calls) == 2


def test_stops_after_max_retries() -> None:
    nohead, calls = make_sync([httpx.ConnectError("refused")], max_retries=0)
    with pytest.raises(APIConnectionError):
        nohead.records.get("r")
    assert len(calls.calls) == 1


def test_timeouts() -> None:
    nohead, _ = make_sync([httpx.ReadTimeout("slow")], max_retries=0)
    with pytest.raises(APITimeoutError):
        nohead.records.get("r")


async def test_async_retries() -> None:
    nohead, calls = make_async(
        [api_error(503, "service_unavailable", NOW), json_response(200, record("r"))]
    )
    assert (await nohead.records.get("r")).id == "r"
    assert len(calls.calls) == 2
