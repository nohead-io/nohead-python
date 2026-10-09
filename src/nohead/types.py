"""Types of the SDK's method parameters (the API's resources are in nohead.models)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import Protocol, TypeAlias, TypedDict

FilterValue: TypeAlias = str | int | float | bool | datetime | date | None


class FilterOperators(TypedDict, total=False):
    """Operators for one key. `ne` matches records without a value; on fields with
    several values `eq`, `ne` and `in` mean contains, does not contain and contains
    any of. Ranges take numbers and dates (`"today"`, `"now"`, or a day, which covers
    that day in the field's time zone)."""

    eq: FilterValue
    ne: FilterValue
    gt: FilterValue
    gte: FilterValue
    lt: FilterValue
    lte: FilterValue
    # `in` is a keyword: pass {"in": [...]} as a plain dict.
    exists: bool


RecordFilter: TypeAlias = Mapping[
    str, FilterValue | FilterOperators | Mapping[str, FilterValue | Sequence[FilterValue]]
]
"""Filters, combined with AND: a value to equal, or operators, e.g.
`{"status": "published", "price": {"lt": 50}, "category": {"in": ["shoes", "bags"]}}`.
Record lists and counts also filter `created_at`, `updated_at` and `published_at`.
None values are left out."""

RecordSort: TypeAlias = str
"""`id`, `created_at`, `updated_at`, `published_at` or a field's API key (records
without a value last); `-` for descending, e.g. `"-published_at"`."""


class HasRevision(Protocol):
    """Anything with a `revision`, such as a Record: `if_match=record`."""

    @property
    def revision(self) -> int: ...


IfMatch: TypeAlias = int | HasRevision
