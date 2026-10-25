"""Retries and timeouts, with each client (the `make` fixture)."""

from __future__ import annotations

import random
import time

import httpx
import pytest

from nohead import (
    APIConnectionError,
    APIError,
    APITimeoutError,
    InternalServerError,
    _base,
)

from .conftest import BACKOFF, Make, api_error, json_response, record, resolve

NOW = {"retry-after": "0"}
BACKOFF_WAIT = 0.25
"""What the backoff waits in test_retries_what_can_succeed_on_a_retry."""


def in_progress(*codes: str) -> httpx.Response:
    details = [{"code": code, "message": f"{code} message"} for code in codes]
    return api_error(409, "conflict", details=details)


# The first attempt's reply, and the seconds waited before the one retry, or None when
# it is not retried.
RETRIES: list[tuple[str, httpx.Response | Exception, list[float] | None]] = [
    ("409 in progress", in_progress("in_progress"), [BACKOFF_WAIT]),
    ("409 in progress among others", in_progress("taken", "in_progress"), [BACKOFF_WAIT]),
    ("409 not in progress", in_progress("taken"), None),
    ("409 without details", api_error(409, "conflict"), None),
    ("400", api_error(400, "invalid_request"), None),
    ("401", api_error(401, "authentication_error"), None),
    ("402", api_error(402, "plan_limit_exceeded"), None),
    ("403", api_error(403, "authorization_error"), None),
    ("404", api_error(404, "not_found"), None),
    ("412", api_error(412, "precondition_failed"), None),
    ("422", api_error(422, "validation_error"), None),
    ("429", api_error(429, "rate_limited"), [BACKOFF_WAIT]),
    ("500", api_error(500, "internal_error"), [BACKOFF_WAIT]),
    ("502", api_error(502, "internal_error"), [BACKOFF_WAIT]),
    ("503", api_error(503, "service_unavailable"), [BACKOFF_WAIT]),
    ("504", api_error(504, "internal_error"), [BACKOFF_WAIT]),
    ("429 Retry-After", api_error(429, "rate_limited", {"retry-after": "3"}), [3]),
    ("503 Retry-After", api_error(503, "service_unavailable", {"retry-after": "7"}), [7]),
    ("Retry-After 0", api_error(503, "service_unavailable", NOW), [0]),
    ("Retry-After at the cap", api_error(429, "rate_limited", {"retry-after": "60"}), [60]),
    ("Retry-After over the cap", api_error(429, "rate_limited", {"retry-after": "60.5"}), None),
    ("Retry-After long", api_error(503, "service_unavailable", {"retry-after": "120"}), None),
    (
        "Retry-After unreadable",
        api_error(503, "service_unavailable", {"retry-after": "soon"}),
        [BACKOFF_WAIT],
    ),
    ("connection error", httpx.ConnectError("refused"), [BACKOFF_WAIT]),
    ("timeout", httpx.ReadTimeout("slow"), [BACKOFF_WAIT]),
]


@pytest.mark.parametrize(
    ("first", "expected"), [case[1:] for case in RETRIES], ids=[case[0] for case in RETRIES]
)
async def test_retries_what_can_succeed_on_a_retry(
    make: Make,
    first: httpx.Response | Exception,
    expected: list[float] | None,
    waits: list[float],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_base, "backoff", lambda attempt: BACKOFF_WAIT)  # pyright: ignore[reportUnknownLambdaType]
    nohead, calls = make([first, json_response(201, record("rec_1"))])
    if expected is None:
        with pytest.raises(APIError) as caught:
            await resolve(nohead.records.create("posts", data={}))
        assert isinstance(first, httpx.Response)
        assert caught.value.status == first.status_code
        assert len(calls.calls) == 1
        assert waits == []
    else:
        assert (await resolve(nohead.records.create("posts", data={}))).id == "rec_1"
        assert waits == expected
        # The retry is the same request: the API runs it at most once.
        keys = [call.headers["idempotency-key"] for call in calls.calls]
        assert len(keys) == 2 and keys[0] == keys[1]


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


async def test_reads_a_retry_after_date(
    make: Make, waits: list[float], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(time, "time", lambda: 1790942400.0)  # 2026-10-02 12:00 UTC
    retry_at = {"retry-after": "Fri, 02 Oct 2026 12:00:05 GMT"}
    nohead, _ = make([api_error(429, "rate_limited", retry_at), json_response(200, record("r"))])
    await resolve(nohead.records.get("r"))
    assert waits == [5]


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
