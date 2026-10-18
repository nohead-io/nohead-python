"""Types of the SDK's method parameters (the API's resources are in nohead.models)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import Literal, Protocol, TypeAlias, TypedDict

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
`{"published_at": {"exists": True}, "price": {"lt": 50}, "category": {"in": ["shoes", "bags"]}}`.
`published_at` with `exists` says whether records are published; record lists and
counts also filter `created_at`, `updated_at` and `published_at` by range, and
`{"deleted": True}` lists deleted records instead.
None values are left out."""


class TimeRange(TypedDict, total=False):
    """A time range, e.g. `{"gte": datetime(2026, 10, 1, tzinfo=UTC)}`."""

    gte: datetime | str
    gt: datetime | str
    lte: datetime | str
    lt: datetime | str


class RevisionFilter(TypedDict, total=False):
    """Filters of `records.revisions.list`, combined with AND."""

    operation: Literal[
        "create",
        "update",
        "publish",
        "unpublish",
        "delete",
        "restore",
        "revert",
        "migrate",
        "merge",
    ]
    """What made the revision; `merge` is a draft's changes."""
    actor_id: str
    """A user (`usr_...`) or API key (`key_...`)."""
    created_at: TimeRange


class AuditEventFilter(TypedDict, total=False):
    """Filters of `audit_events.list`, combined with AND."""

    type: str
    """The event's type, exactly (`field.updated`) or by prefix (`record.*`)."""
    resource_type: str | Sequence[str]
    """What the event is about (`record`, `draft`, `collection`, `field`, `asset`,
    `webhook`, ...), or any of several."""
    resource_id: str
    actor_type: Literal["user", "api_key", "system"]
    actor_id: str
    """A user (`usr_...`) or API key (`key_...`)."""
    created_at: TimeRange


class Exists(TypedDict):
    exists: bool


class SearchFilter(TypedDict, total=False):
    """Filters of project-wide search (`nohead.search`); its `collections` narrows it to
    some collections."""

    published_at: Exists
    """`{"exists": True}` finds published records only, `False` unpublished ones."""


RecordSort: TypeAlias = str
"""`created_at`, `updated_at`, `published_at` or a field's API key (records without a
value last); `-` for descending, e.g. `"-published_at"`."""


class HasRevision(Protocol):
    """Anything with a `revision`, such as a Record: `if_match=record`."""

    @property
    def revision(self) -> int: ...


IfMatch: TypeAlias = int | HasRevision
