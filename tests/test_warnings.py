"""Deprecation and plan usage warnings (the `warnings` option), with each client (the
`make` fixture). conftest.py forgets what was warned about before each test."""

from __future__ import annotations

import os
import warnings

import pytest

import nohead
from nohead import NoheadWarning

from .conftest import Make, items, json_response, page, record, resolve

SDK = os.path.dirname(nohead.__file__) + os.sep
"""Warnings point at the code that called the SDK (or iterated its pages), not inside it."""

SUNSET = "Sat, 31 Oct 2026 00:00:00 GMT"
DEPRECATED = {
    "deprecation": "@1790942400",
    "sunset": SUNSET,
    "link": '<https://nohead.io/docs/changelog>; rel="deprecation"',
}
OVER_A_LIMIT = {"nohead-usage-warning": "records: 9,500 of 10,000"}


async def test_warns_once_per_deprecated_operation(make: Make) -> None:
    nohead, _ = make([json_response(200, record("rec_1"), DEPRECATED)])
    with pytest.warns(NoheadWarning) as warned:
        await resolve(nohead.records.get("rec_1"))
        await resolve(nohead.records.get("rec_1"))
        await resolve(nohead.records.publish("rec_1"))
    assert [str(w.message) for w in warned] == [
        f"{operation} is deprecated and will be removed after {SUNSET}. "
        "See https://nohead.io/docs/changelog"
        for operation in ("records_get", "records_publish")
    ]
    assert not any(w.filename.startswith(SDK) for w in warned)


async def test_names_only_the_deprecation_without_a_sunset_or_link(make: Make) -> None:
    nohead, _ = make([json_response(200, record("rec_1"), {"deprecation": "true"})])
    with pytest.warns(NoheadWarning) as warned:
        await resolve(nohead.records.get("rec_1"))
    assert [str(w.message) for w in warned] == ["records_get is deprecated"]


async def test_warns_once_about_usage_over_a_plan_limit(make: Make) -> None:
    nohead, _ = make([json_response(200, record("rec_1"), OVER_A_LIMIT)])
    with pytest.warns(NoheadWarning) as warned:
        await resolve(nohead.records.get("rec_1"))
        await resolve(nohead.records.publish("rec_1"))
    assert [str(w.message) for w in warned] == ["Over a plan limit: records: 9,500 of 10,000"]
    assert not warned[0].filename.startswith(SDK)


async def test_warns_at_the_loop_that_fetched_the_page(make: Make) -> None:
    nohead, _ = make(
        [
            page([record("rec_1")], "c2", has_more=True),
            json_response(
                200, {"data": [], "meta": {"next_cursor": None, "has_more": False}}, DEPRECATED
            ),
        ]
    )
    with pytest.warns(NoheadWarning, match="records_list is deprecated") as warned:
        await items(nohead.records.list("posts"))
    assert not warned[0].filename.startswith(SDK)


async def test_warns_about_nothing_when_turned_off(make: Make) -> None:
    reply = json_response(200, record("rec_1"), DEPRECATED | OVER_A_LIMIT)
    nohead, _ = make([reply], warnings=False)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        await resolve(nohead.records.get("rec_1"))
        await resolve(nohead.records.publish("rec_1"))
