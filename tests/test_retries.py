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
    NoheadError,
    RetryEvent,
    ServiceUnavailableError,
    _base,
)

from .conftest import BACKOFF, Make, api_error, json_response, record, resolve
from .spec import example_of

NOW = {"retry-after": "0"}
LAST_PAGE_BODY = {"data": [], "meta": {"next_cursor": None, "has_more": False}}
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
    ("Retry-After fraction", api_error(429, "rate_limited", {"retry-after": "1.5"}), [1.5]),
    ("Retry-After spaced", api_error(429, "rate_limited", {"retry-after": " 2 "}), [2]),
    *[
        (
            f"Retry-After {value}",
            api_error(429, "rate_limited", {"retry-after": value}),
            [BACKOFF_WAIT],
        )
        for value in ["-1", "+5", ".5", "5.", "1e3", "inf", "nan", "0x10", "2026-10-02T12:00:05Z"]
    ],
    ("connection error", httpx.ConnectError("refused"), [BACKOFF_WAIT]),
    ("dropped connection", httpx.RemoteProtocolError("Server disconnected"), [BACKOFF_WAIT]),
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


@pytest.mark.parametrize(
    "error",
    [
        httpx.UnsupportedProtocol("Request URL has an unsupported protocol 'ftp://'."),
        httpx.LocalProtocolError("Illegal header value"),
    ],
)
async def test_does_not_retry_a_request_that_cannot_be_sent(
    make: Make, error: httpx.TransportError, waits: list[float]
) -> None:
    nohead, calls = make([error])
    with pytest.raises(NoheadError, match="Could not send the request") as caught:
        await resolve(nohead.records.get("r"))
    assert not isinstance(caught.value, APIConnectionError)
    assert len(calls.calls) == 1
    assert waits == []


async def test_does_not_retry_an_upload_that_cannot_be_sent(make: Make) -> None:
    created = json_response(
        201,
        {
            **example_of("Asset", id="ast_1", project_id="prj_1", status="pending"),
            "upload": {
                "method": "PUT",
                "url": "ftp://storage.test/uploads/ast_1",
                "headers": {},
                "expires_at": "2999-01-01T00:00:00Z",
            },
        },
    )
    nohead, calls = make([created, httpx.UnsupportedProtocol("unsupported protocol")])
    with pytest.raises(NoheadError, match="Could not send the request"):
        await resolve(nohead.assets.upload(b"x"))
    assert [c.method for c in calls.calls] == ["POST", "PUT"]


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


@pytest.mark.parametrize(
    "value",
    [
        "Fri, 02 Oct 2026 12:00:05 GMT",
        "Friday, 02-Oct-26 12:00:05 GMT",
        "Fri Oct  2 12:00:05 2026",
    ],
    ids=["IMF-fixdate", "RFC 850", "asctime"],
)
async def test_reads_retry_after_dates_in_every_http_form_as_gmt(
    make: Make, waits: list[float], monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    # Far from UTC, so a date read as local time would be hours off.
    monkeypatch.setenv("TZ", "America/Los_Angeles")
    time.tzset()
    monkeypatch.setattr(time, "time", lambda: 1790942400.0)  # 2026-10-02 12:00 UTC
    try:
        nohead, _ = make(
            [
                api_error(429, "rate_limited", {"retry-after": value}),
                json_response(200, record("r")),
            ]
        )
        await resolve(nohead.records.get("r"))
    finally:
        monkeypatch.undo()
        time.tzset()
    assert waits == [5]


async def test_reports_each_retry_to_on_retry(make: Make, waits: list[float]) -> None:
    events: list[RetryEvent] = []
    nohead, _ = make(
        [
            api_error(503, "service_unavailable", {"retry-after": "2"}),
            httpx.ConnectError("refused"),
            json_response(200, LAST_PAGE_BODY),
        ],
        on_retry=events.append,
    )
    await resolve(nohead.records.list("posts", limit=5))
    url = "https://api.test/v1/collections/posts/records?limit=5"
    assert [(e.attempt, e.delay, e.url, e.status) for e in events] == [
        (1, 2, url, 503),
        (2, 0, url, None),
    ]
    assert waits == [2, 0]
    assert isinstance(events[0].error, ServiceUnavailableError)
    assert isinstance(events[1].error, APIConnectionError)
    assert str(events[1].error) == "Could not reach api.test: refused"


async def test_on_retry_is_not_called_without_a_retry(make: Make) -> None:
    events: list[RetryEvent] = []
    nohead, _ = make([api_error(500, "internal_error")], max_retries=0, on_retry=events.append)
    with pytest.raises(InternalServerError):
        await resolve(nohead.records.get("r"))
    assert events == []


async def test_takes_on_retry_per_client_copy(make: Make) -> None:
    first: list[RetryEvent] = []
    second: list[RetryEvent] = []
    nohead, _ = make([api_error(500, "internal_error")], max_retries=1, on_retry=first.append)
    copy = nohead.with_options(on_retry=second.append)
    with pytest.raises(InternalServerError):
        await resolve(copy.records.get("r"))
    with pytest.raises(InternalServerError):
        await resolve(nohead.with_options(timeout=5).records.get("r"))
    assert (len(first), len(second)) == (1, 1)
