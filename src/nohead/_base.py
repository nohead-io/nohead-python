"""What the sync and async clients share: settings, request building, retry rules."""

from __future__ import annotations

import json
import os
import platform
import random
import typing
import uuid
import warnings as _warnings
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from functools import cache
from typing import Any
from urllib.parse import quote

import httpx
from pydantic import BaseModel, TypeAdapter
from pydantic import ValidationError as PydanticValidationError

from ._errors import APIError, NoheadError
from ._version import __version__
from .types import IfMatch

DEFAULT_BASE_URL = "https://api.nohead.io"
RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})
MAX_RETRY_AFTER_SECONDS = 60.0


class NoheadWarning(UserWarning):
    """A deprecated operation, or usage over a soft plan limit. Shown once each."""


_warned_deprecations: set[str] = set()
_warned_shapes: set[str] = set()
_warned_usage = False


@dataclass(frozen=True)
class Settings:
    api_key: str
    base_url: str
    project_id: str | None
    max_retries: int
    timeout: float
    headers: Mapping[str, str] = field(default_factory=dict[str, str])
    warnings: bool = True


def settings(
    *,
    api_key: str | None,
    base_url: str | None,
    project_id: str | None,
    max_retries: int,
    timeout: float,
    headers: Mapping[str, str] | None,
    warnings: bool,
) -> Settings:
    # Empty environment variables count as unset.
    api_key = api_key or os.environ.get("NOHEAD_API_KEY") or None
    if not api_key:
        raise NoheadError("Missing API key: pass api_key or set NOHEAD_API_KEY")
    base_url = base_url or os.environ.get("NOHEAD_API_URL") or DEFAULT_BASE_URL
    return Settings(
        api_key=api_key,
        base_url=base_url.rstrip("/"),
        project_id=project_id,
        max_retries=max_retries,
        timeout=timeout,
        headers=dict(headers or {}),
        warnings=warnings,
    )


def url(settings: Settings, template: str, values: Mapping[str, str | int]) -> str:
    path = template
    for name, value in values.items():
        path = path.replace("{" + name + "}", quote(str(value), safe=""))
    if "{" in path:
        raise NoheadError(f"Missing a path parameter of {template}")
    return settings.base_url + path


def query(params: Mapping[str, Any] | None) -> tuple[tuple[str, str], ...]:
    """Query parameters as the API reads them: mappings become `key[sub]=...`
    (`filter[status]=published`), lists are comma-separated (`expand=author,tags`),
    booleans are `true`/`false`, dates ISO 8601. None values are left out."""
    out: list[tuple[str, str]] = []

    def add(key: str, value: Any) -> None:
        if value is None:
            return
        if isinstance(value, Mapping):
            for name, inner in value.items():  # pyright: ignore[reportUnknownVariableType]
                add(f"{key}[{name}]", inner)
        elif isinstance(value, list | tuple):
            items = [scalar(v) for v in value if v is not None]  # pyright: ignore[reportUnknownVariableType]
            if items:
                out.append((key, ",".join(items)))
        else:
            out.append((key, scalar(value)))

    for key, value in (params or {}).items():
        add(key, value)
    return tuple(out)


def scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, datetime | date):
        return iso(value)
    return str(value)


def iso(value: datetime | date) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(UTC)
        return value.isoformat().replace("+00:00", "Z")
    return value.isoformat()


def encode(body: Any) -> bytes:
    def default(value: Any) -> Any:
        if isinstance(value, datetime | date):
            return iso(value)
        raise TypeError(f"{type(value).__name__} is not JSON serializable")

    return json.dumps(body, default=default, separators=(",", ":")).encode()


USER_AGENT = f"nohead-python/{__version__} python/{platform.python_version()}"


def headers(
    settings: Settings,
    method: str,
    *,
    has_body: bool,
    idempotency_key: str | None,
    change_note: str | None,
    if_match: IfMatch | None,
) -> dict[str, str]:
    out = {
        "Accept": "application/json",
        "Authorization": f"Bearer {settings.api_key}",
        "Nohead-Client": f"sdk-python/{__version__}",
        "User-Agent": USER_AGENT,
        **settings.headers,
    }
    if has_body:
        out["Content-Type"] = "application/json"
    if method != "GET":
        out["Idempotency-Key"] = idempotency_key or str(uuid.uuid4())
    if if_match is not None:
        revision = if_match if isinstance(if_match, int) else if_match.revision
        out["If-Match"] = f'"{revision}"'
    if change_note:
        out["Nohead-Change-Note"] = change_note
    return out


@cache
def _adapter(kind: Any) -> TypeAdapter[Any]:
    return TypeAdapter(kind)


def validate(kind: Any, data: Any) -> Any:
    """`data` as `kind`. A response that does not match the SDK's models (a newer API)
    is still returned, unvalidated, with a warning, rather than raised."""
    try:
        return _adapter(kind).validate_python(data)
    except PydanticValidationError as error:
        name = getattr(kind, "__name__", str(kind))
        if name in _warned_shapes:
            return _unvalidated(kind, data)
        _warned_shapes.add(name)
        _warnings.warn(
            f"The API's response did not match the SDK's {name} "
            f"model; returning it unvalidated ({error.error_count()} differences). "
            "Updating the SDK should fix this.",
            NoheadWarning,
            stacklevel=4,
        )
        return _unvalidated(kind, data)


def _unvalidated(kind: Any, data: Any) -> Any:
    """`data` built into `kind` without validation, nested models included."""
    if isinstance(data, list):
        (item,) = typing.get_args(kind) or (Any,)
        return [_unvalidated(item, value) for value in data]  # pyright: ignore[reportUnknownVariableType]
    if not isinstance(data, dict):
        return data
    model = _model_of(kind)
    if model is None:
        return data  # pyright: ignore[reportUnknownVariableType]
    raw: dict[str, Any] = data  # pyright: ignore[reportUnknownVariableType]
    values: dict[str, Any] = {}
    known: set[str] = set()
    for name, info in model.model_fields.items():
        key = info.alias or name
        known.add(key)
        if key in raw:
            values[name] = _unvalidated(info.annotation, raw[key])
    extra = {key: value for key, value in raw.items() if key not in known}
    built = model.model_construct(**values)
    if extra:
        object.__setattr__(built, "__pydantic_extra__", extra)
    return built


def _model_of(kind: Any) -> type[BaseModel] | None:
    """The model class in `kind`, also inside `X | None` and `list[X]`."""
    if isinstance(kind, type) and issubclass(kind, BaseModel):
        return kind
    for arg in typing.get_args(kind):
        if isinstance(arg, type) and issubclass(arg, BaseModel):
            return arg
    return None


def parse(response: httpx.Response) -> Any:
    if not response.content:
        return None
    if "json" not in response.headers.get("content-type", ""):
        return response.text
    try:
        return response.json()
    except ValueError:
        return response.text


def retry_delay(error: APIError, attempt: int, max_retries: int) -> float | None:
    """Seconds to wait before retrying `error`, or None to raise it."""
    from ._errors import retry_after_seconds

    if attempt >= max_retries:
        return None
    in_progress = error.status == 409 and any(d.code == "in_progress" for d in error.details)
    if not in_progress and error.status not in RETRYABLE_STATUSES:
        return None
    retry_after = retry_after_seconds(error.headers)
    if retry_after is None:
        return backoff(attempt)
    return retry_after if retry_after <= MAX_RETRY_AFTER_SECONDS else None


def backoff(attempt: int) -> float:
    """Exponential backoff with jitter: about 0.5 s, 1 s, 2 s... up to 8 s."""
    return min(0.5 * 2**attempt, 8.0) * (1 - random.random() * 0.25)


def warn(settings: Settings, operation: str, response: httpx.Response) -> None:
    global _warned_usage
    if not settings.warnings:
        return
    if response.headers.get("deprecation") and operation not in _warned_deprecations:
        _warned_deprecations.add(operation)
        sunset = response.headers.get("sunset")
        link = response.headers.get("link", "").partition("<")[2].partition(">")[0]
        message = f"{operation} is deprecated"
        if sunset:
            message += f" and will be removed after {sunset}"
        if link:
            message += f". See {link}"
        _warnings.warn(message, NoheadWarning, stacklevel=4)
    usage = response.headers.get("nohead-usage-warning")
    if usage and not _warned_usage:
        _warned_usage = True
        _warnings.warn(f"Over a plan limit: {usage}", NoheadWarning, stacklevel=4)
