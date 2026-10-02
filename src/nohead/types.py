"""Types of the SDK's method parameters (the API's resources are in nohead.models)."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Literal, Protocol, TypeAlias

FilterValue: TypeAlias = str | int | float | bool | datetime | None

RecordFilter: TypeAlias = Mapping[str, FilterValue]
"""Equality filters, e.g. `{"status": "published", "author": "rec_..."}`. For fields
with several values a filter means "contains". None values are left out."""

RecordSort: TypeAlias = Literal[
    "created_at",
    "-created_at",
    "updated_at",
    "-updated_at",
    "published_at",
    "-published_at",
    "id",
    "-id",
]


class HasRevision(Protocol):
    """Anything with a `revision`, such as a Record: `if_match=record`."""

    @property
    def revision(self) -> int: ...


IfMatch: TypeAlias = int | HasRevision
