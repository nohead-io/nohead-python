"""Retries and timeouts, with each client (the `make` fixture)."""

from __future__ import annotations

import random
import time

import httpx
import pytest

from nohead import (
    APIConnectionError,
    APITimeoutError,
    InternalServerError,
    RateLimitError,
    ValidationError,
    _base,
)

from .conftest import BACKOFF, Make, api_error, json_response, record, resolve

NOW = {"retry-after": "0"}


async def test_retries_server_errors_with_one_idempotency_key(make: Make) -> None:
    nohead, calls = make(
        [
            api_error(500, "internal_error", NOW),
            api_error(503, "service_unavailable", NOW),
            json_response(201, record("rec_1")),
        ]
    )
    assert (await resolve(nohead.records.create("posts", data={}))).id == "rec_1"
    assert len(calls.calls) == 3
    assert len({c.headers["idempotency-key"] for c in calls.calls}) == 1


@pytest.mark.parametrize("status", [502, 504])
async def test_retries_gateway_errors(make: Make, status: int) -> None:
    nohead, calls = make([api_error(status, "internal_error"), json_response(200, record("r"))])
    await resolve(nohead.records.get("r"))
    assert len(calls.calls) == 2


async def test_gives_up_after_the_default_two_retries(make: Make) -> None:
    nohead, calls = make([api_error(500, "internal_error")])
    with pytest.raises(InternalServerError):
        await resolve(nohead.records.get("r"))
    assert len(calls.calls) == 3


async def test_backs_off_exponentially_with_jitter_up_to_8_s(
    make: Make, waits: list[float], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(_base, "backoff", BACKOFF)
    monkeypatch.setattr(random, "random", lambda: 0.5)  # 12.5% off each delay
    nohead, _ = make([api_error(500, "internal_error")], max_retries=6)
    with pytest.raises(InternalServerError):
        await resolve(nohead.records.get("r"))
    assert waits == [0.4375, 0.875, 1.75, 3.5, 7, 7]


async def test_waits_out_a_short_retry_after(make: Make, waits: list[float]) -> None:
    nohead, calls = make(
        [api_error(429, "rate_limited", {"retry-after": "3"}), json_response(200, record("r"))]
    )
    await resolve(nohead.records.get("r"))
    assert waits == [3]
    assert len(calls.calls) == 2


async def test_reads_a_retry_after_date(
    make: Make, waits: list[float], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(time, "time", lambda: 1790942400.0)  # 2026-10-02 12:00 UTC
    retry_at = {"retry-after": "Fri, 02 Oct 2026 12:00:05 GMT"}
    nohead, _ = make([api_error(429, "rate_limited", retry_at), json_response(200, record("r"))])
    await resolve(nohead.records.get("r"))
    assert waits == [5]


async def test_backs_off_on_a_429_without_retry_after(
    make: Make, waits: list[float], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(_base, "backoff", BACKOFF)
    monkeypatch.setattr(random, "random", lambda: 0.0)
    nohead, calls = make([api_error(429, "rate_limited"), json_response(200, record("r"))])
    await resolve(nohead.records.get("r"))
    assert waits == [0.5]
    assert len(calls.calls) == 2


async def test_gives_up_on_a_long_retry_after(make: Make) -> None:
    nohead, calls = make([api_error(429, "rate_limited", {"retry-after": "120"})])
    with pytest.raises(RateLimitError):
        await resolve(nohead.records.get("r"))
    assert len(calls.calls) == 1


async def test_retries_a_request_in_progress(make: Make) -> None:
    busy = api_error(409, "conflict", NOW, details=[{"code": "in_progress", "message": "..."}])
    nohead, calls = make([busy, json_response(201, record("r"))])
    await resolve(nohead.records.create("posts", data={}))
    assert len(calls.calls) == 2


async def test_does_not_retry_other_client_errors(make: Make) -> None:
    nohead, calls = make([api_error(422, "validation_error")])
    with pytest.raises(ValidationError):
        await resolve(nohead.records.create("posts", data={}))
    assert len(calls.calls) == 1


async def test_retries_connection_failures(make: Make) -> None:
    nohead, calls = make([httpx.ConnectError("refused"), json_response(200, record("r"))])
    await resolve(nohead.records.get("r"))
    assert len(calls.calls) == 2


async def test_stops_after_max_retries(make: Make) -> None:
    nohead, calls = make([httpx.ConnectError("refused")], max_retries=0)
    with pytest.raises(APIConnectionError):
        await resolve(nohead.records.get("r"))
    assert len(calls.calls) == 1


async def test_takes_max_retries_and_timeout_per_client_copy(make: Make) -> None:
    nohead, calls = make([api_error(500, "internal_error")], timeout=60)
    with pytest.raises(InternalServerError):
        await resolve(nohead.with_options(max_retries=0, timeout=5).records.get("r"))
    assert len(calls.calls) == 1
    assert calls.calls[0].extensions["timeout"] == {
        "connect": 5,
        "read": 5,
        "write": 5,
        "pool": 5,
    }


async def test_times_out_slow_attempts(make: Make) -> None:
    nohead, calls = make([httpx.ReadTimeout("slow")], max_retries=0, timeout=7)
    with pytest.raises(APITimeoutError):
        await resolve(nohead.records.get("r"))
    assert calls.calls[0].extensions["timeout"]["read"] == 7


async def test_retries_a_timeout(make: Make) -> None:
    nohead, calls = make([httpx.ReadTimeout("slow"), json_response(200, record("r"))])
    assert (await resolve(nohead.records.get("r"))).id == "r"
    assert len(calls.calls) == 2
