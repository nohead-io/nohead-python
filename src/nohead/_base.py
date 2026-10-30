"""What the sync and async clients share: settings, request building, retry rules."""

from __future__ import annotations

import asyncio
import inspect
import json
import os
import platform
import random
import re
import threading
import types
import typing
import urllib.parse
import uuid
import warnings as _warnings
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from functools import cache
from typing import Any, Generic, TypeVar, cast
from urllib.parse import quote

import httpx
from pydantic import BaseModel, TypeAdapter
from pydantic import ValidationError as PydanticValidationError

from ._errors import APIError, NoheadError, retry_after_seconds
from ._version import __version__
from .types import IfMatch, RetryEvent

T = TypeVar("T")

DEFAULT_BASE_URL = "https://api.nohead.io"
RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})
RETRYABLE_TRANSPORT_ERRORS = (
    httpx.TimeoutException,
    httpx.NetworkError,
    httpx.RemoteProtocolError,  # a dropped connection
    httpx.ProxyError,
)
"""Transport errors a retry can fix. The others (an unsupported URL scheme, a header
httpx can't send) fail the same way every time."""
MAX_RETRY_AFTER_SECONDS = 60.0


class NoheadWarning(UserWarning):
    """A deprecated operation, or usage over a soft plan limit. Shown once each."""


# Resolved, so a symlinked install compares like for like.
_PACKAGE = os.path.dirname(os.path.realpath(__file__)) + os.sep


def _outside_the_sdk() -> int:
    """The `stacklevel` that points a warning at the code that called the SDK, for the
    function that calls this one: the number of frames up to the first one outside the
    package (a method, a page fetched while iterating, a model's property...)."""
    here = inspect.currentframe()
    frame = here.f_back if here is not None else None  # the function that warns
    level = 1
    while frame is not None and os.path.realpath(frame.f_code.co_filename).startswith(_PACKAGE):
        frame = frame.f_back
        level += 1
    return level


_warned: set[str] = set()
_warned_lock = threading.Lock()


def first_warning(key: str) -> bool:
    """Whether `key` hasn't been warned about yet in this process (then it has)."""
    with _warned_lock:
        if key in _warned:
            return False
        _warned.add(key)
        return True


@dataclass(frozen=True)
class Settings:
    api_key: str
    base_url: str
    project_id: str | None
    max_retries: int
    timeout: float
    headers: Mapping[str, str] = field(default_factory=dict[str, str])
    warnings: bool = True
    on_retry: Callable[[RetryEvent], object] | None = None


def settings(
    *,
    api_key: str | None,
    base_url: str | None,
    project_id: str | None,
    max_retries: int,
    timeout: float,
    headers: Mapping[str, str] | None,
    warnings: bool,
    on_retry: Callable[[RetryEvent], object] | None,
) -> Settings:
    # Empty values, given or from the environment, count as unset.
    api_key = api_key or os.environ.get("NOHEAD_API_KEY") or None
    if not api_key:
        raise NoheadError("Missing API key: pass api_key or set NOHEAD_API_KEY")
    # Never from the environment, so the key only goes where the code says.
    base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
    if not _is_http_url(base_url):
        raise NoheadError("base_url must be an http or https URL")
    return Settings(
        api_key=api_key,
        base_url=base_url,
        project_id=project_id or None,
        max_retries=max_retries,
        timeout=timeout,
        headers=merge_headers(headers or {}),
        warnings=warnings,
        on_retry=on_retry,
    )


def _is_http_url(value: str) -> bool:
    try:
        parts = urllib.parse.urlsplit(value)
        return parts.scheme.lower() in ("http", "https") and bool(parts.hostname)
    except ValueError:  # not a URL, such as an unclosed IPv6 address
        return False


def url(settings: Settings, template: str, values: Mapping[str, str | int]) -> str:
    # A value the template doesn't take is a method out of step with its operation.
    if unknown := set(values) - set(re.findall(r"\{(\w+)\}", template)):
        raise TypeError(f"{', '.join(sorted(unknown))} is not a path parameter of {template}")

    def value(match: re.Match[str]) -> str:
        name = match[1]
        if values.get(name) in (None, ""):
            raise NoheadError(f"Missing {name}")
        text = str(values[name])
        # Encoded or not, URL parsers resolve these as the current or parent path.
        if text in (".", ".."):
            raise NoheadError(f'Invalid {name}: "{text}"')
        return quote(text, safe="")

    return settings.base_url + re.sub(r"\{(\w+)\}", value, template)


def one_or_in(value: str | Sequence[str] | None) -> str | dict[str, list[str]] | None:
    """A filter value as the API takes it: one as it is, several as `{"in": [...]}`."""
    return value if value is None or isinstance(value, str) else {"in": list(value)}


def query(params: Mapping[str, Any] | None) -> tuple[tuple[str, str], ...]:
    """Query parameters as the API reads them: mappings become `key[sub]=...`
    (`filter[price][lt]=50`), lists are comma-separated (`expand=author,tags`) with
    `\\,` for a comma inside a value and `\\\\` for a backslash, booleans are
    `true`/`false`, dates ISO 8601. None values are left out."""
    out: list[tuple[str, str]] = []

    def add(key: str, value: Any) -> None:
        if value is None:
            return
        if isinstance(value, Mapping):
            for name, inner in value.items():  # pyright: ignore[reportUnknownVariableType]
                add(f"{key}[{name}]", inner)
        elif isinstance(value, list | tuple):
            items = [escape(scalar(v)) for v in value if v is not None]  # pyright: ignore[reportUnknownVariableType]
            if items:
                out.append((key, ",".join(items)))
        else:
            out.append((key, scalar(value)))

    for key, value in (params or {}).items():
        add(key, value)
    return tuple(out)


def escape(item: str) -> str:
    """A list item with its backslashes and commas escaped."""
    return item.replace("\\", "\\\\").replace(",", "\\,")


def scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, datetime | date):
        return iso(value)
    return str(value)


def iso(value: datetime | date) -> str:
    if isinstance(value, datetime):
        # A naive datetime's moment depends on where the code runs: the API can't tell.
        if value.utcoffset() is None:
            raise ValueError(
                f"The datetime {value.isoformat()} has no time zone: pass an aware datetime"
            )
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    return value.isoformat()


def encode(body: Any) -> bytes:
    def default(value: Any) -> Any:
        if isinstance(value, datetime | date):
            return iso(value)
        raise TypeError(f"{type(value).__name__} is not JSON serializable")

    # NaN and infinities aren't JSON: refuse them (ValueError) rather than send them.
    return json.dumps(body, default=default, separators=(",", ":"), allow_nan=False).encode()


USER_AGENT = f"nohead-python/{__version__} python/{platform.python_version()}"


def merge_headers(*layers: Mapping[str, str]) -> dict[str, str]:
    """Headers with each name once, matched without regard to case: a later layer's
    value (and spelling of the name) replaces an earlier one's."""
    merged: dict[str, tuple[str, str]] = {}
    for layer in layers:
        for name, value in layer.items():
            merged[name.lower()] = (name, value)
    return dict(merged.values())


def headers(
    settings: Settings,
    method: str,
    *,
    has_body: bool,
    idempotency_key: str | None,
    change_note: str | None,
    if_match: IfMatch | None,
) -> dict[str, str]:
    defaults = {
        "Accept": "application/json",
        "Authorization": f"Bearer {settings.api_key}",
        "Nohead-Client": f"sdk-python/{__version__}",
        "User-Agent": USER_AGENT,
    }
    # The headers the request's options set win over the client's `headers`.
    options: dict[str, str] = {}
    if has_body:
        options["Content-Type"] = "application/json"
    if method != "GET":
        options["Idempotency-Key"] = idempotency_key or str(uuid.uuid4())
    if if_match is not None:
        options["If-Match"] = f'"{revision_of(if_match)}"'
    if change_note:
        # Percent-encoded UTF-8, as encodeURIComponent: header values are
        # bytes (the API decodes it). A lone surrogate becomes U+FFFD.
        # (A Python string holds surrogates only unpaired.)
        well_formed = re.sub("[\ud800-\udfff]", "\ufffd", change_note)
        options["Nohead-Change-Note"] = urllib.parse.quote(well_formed, safe="-_.!~*'()")
    return merge_headers(defaults, settings.headers, options)


def revision_of(if_match: object) -> int:
    """The revision an `if_match` names: a number, or the `revision` of a record or
    draft or of a mapping (`{"revision": 3}`)."""
    revision: object = (
        cast("Mapping[str, object]", if_match).get("revision")
        if isinstance(if_match, Mapping)
        else getattr(if_match, "revision", if_match)
    )
    if not isinstance(revision, int) or isinstance(revision, bool):
        raise TypeError(
            "if_match takes a revision number, or a record, draft or mapping with a revision"
        )
    return revision


@cache
def _adapter(kind: Any) -> TypeAdapter[Any]:
    return TypeAdapter(kind)


def validate(kind: Any, data: Any) -> Any:
    """`data` as `kind`. A response that does not match the SDK's models (a newer API)
    is still returned, unvalidated, with a warning, rather than raised."""
    try:
        return _adapter(kind).validate_python(data)
    except PydanticValidationError as error:
        # Of a union (Field), the model it is returned as.
        model = _model_of(kind, data) if isinstance(data, dict) else None  # pyright: ignore[reportUnknownArgumentType]
        name = model.__name__ if model else getattr(kind, "__name__", str(kind))
        if first_warning(f"shape:{name}"):
            _warnings.warn(
                f"The API's response did not match the SDK's {name} "
                f"model; returning it unvalidated ({error.error_count()} differences). "
                "Updating the SDK should fix this.",
                NoheadWarning,
                stacklevel=_outside_the_sdk(),
            )
        return _unvalidated(kind, data)


def _unvalidated(kind: Any, data: Any) -> Any:
    """`data` built into `kind` without validation, nested models included."""
    if isinstance(data, list):
        item = _item_of(kind)
        return [_unvalidated(item, value) for value in data]  # pyright: ignore[reportUnknownVariableType]
    if not isinstance(data, dict):
        return data
    model = _model_of(kind, data)  # pyright: ignore[reportUnknownArgumentType]
    if model is None:
        return data  # pyright: ignore[reportUnknownVariableType]
    raw: dict[str, Any] = data  # pyright: ignore[reportUnknownVariableType]
    values: dict[str, Any] = {}
    known: set[str] = set()
    for name, info in model.model_fields.items():
        key = info.alias or name
        known.add(key)
        if key in raw:
            values[name] = _field(info.annotation, raw[key])
    extra = {key: value for key, value in raw.items() if key not in known}
    built = model.model_construct(**values)
    if extra:
        object.__setattr__(built, "__pydantic_extra__", extra)
    return built


def _field(kind: Any, value: Any) -> Any:
    """One field of an unvalidated model: nested models and lists as `_unvalidated`
    builds them, and other values validated on their own (a timestamp becomes a
    `datetime`), kept as they came only when that field itself does not match."""
    if isinstance(value, (dict, list)):
        return _unvalidated(kind, value)
    try:
        return _adapter(kind).validate_python(value)
    except PydanticValidationError:
        return value


def _parts(kind: Any) -> list[Any]:
    """The types of a union, `X | None`, also inside `Annotated[...]` (a discriminated
    union, such as Field); `[kind]` when it is not one."""
    origin = typing.get_origin(kind)
    if origin is typing.Annotated:
        return _parts(typing.get_args(kind)[0])
    if origin is typing.Union or origin is types.UnionType:
        return [part for arg in typing.get_args(kind) for part in _parts(arg)]
    return [kind]


def _item_of(kind: Any) -> Any:
    """The item type of `list[X]`, also inside `list[X] | None`; else Any."""
    lists = [part for part in _parts(kind) if typing.get_origin(part) is list]
    return typing.get_args(lists[0])[0] if lists else Any


def _model_of(kind: Any, data: dict[str, Any]) -> type[BaseModel] | None:
    """The model class in `kind`, also inside `X | None`, `list[X]` and `Annotated[X,
    ...]`. Of a union of models, the one `data` fits best: its Literal fields match, and
    its required ones are there."""
    parts = [
        item
        for part in _parts(kind)
        for item in (_parts(_item_of(part)) if typing.get_origin(part) is list else [part])
    ]
    models = [part for part in parts if isinstance(part, type) and issubclass(part, BaseModel)]
    if not models:
        return None
    return max(models, key=lambda model: _fit(model, data))


def _fit(model: type[BaseModel], data: dict[str, Any]) -> tuple[bool, bool]:
    literals = required = True
    for name, info in model.model_fields.items():
        key = info.alias or name
        if typing.get_origin(info.annotation) is typing.Literal:
            literals = literals and data.get(key) in typing.get_args(info.annotation)
        if info.is_required():
            required = required and key in data
    return literals, required


class AsyncOnce(Generic[T]):
    """A value worked out once, by the first call that needs it: calls made while it is
    on its way wait for the same lookup (a task), and share its failure, after which
    the next call tries again."""

    def __init__(self, value: T | None = None) -> None:
        self.value = value
        self._task: asyncio.Task[T] | None = None

    async def get(self, compute: Callable[[], Awaitable[T]]) -> T:
        if self.value is not None:
            return self.value
        task = self._task
        # A task of a loop that has gone (asyncio.run called again) never finishes.
        if task is None or task.get_loop() is not asyncio.get_running_loop():
            task = self._task = asyncio.ensure_future(self._run(compute))
        # Shielded: a caller that is cancelled doesn't cancel the others' lookup.
        return await asyncio.shield(task)

    async def _run(self, compute: Callable[[], Awaitable[T]]) -> T:
        try:
            self.value = await compute()
            return self.value
        finally:
            self._task = None


class Once(Generic[T]):
    """A value worked out once, by the first call that needs it: calls made while it is
    on its way wait for it (a lock), and try again themselves if it failed."""

    def __init__(self, value: T | None = None) -> None:
        self.value = value
        self._lock = threading.Lock()

    def get(self, compute: Callable[[], T]) -> T:
        if self.value is not None:
            return self.value
        with self._lock:
            if self.value is None:
                self.value = compute()
            return self.value


def full_url(url: str, params: tuple[tuple[str, str], ...]) -> str:
    """A request's URL with its query, as on_retry reports it."""
    return str(httpx.URL(url, params=params)) if params else url


def notify_retry(
    settings: Settings,
    attempt: int,
    delay: float,
    url: str,
    *,
    status: int | None = None,
    error: NoheadError | None = None,
) -> None:
    """Tells `on_retry` about a retry before its wait. `attempt` is the failed one,
    counting from 0; the event counts retries from 1."""
    if settings.on_retry is not None:
        settings.on_retry(
            RetryEvent(attempt=attempt + 1, delay=delay, url=url, status=status, error=error)
        )


def list_body(response: httpx.Response) -> dict[str, Any]:
    """A list response's body: an object with a `data` list and a `meta` object."""
    data = parse(response)
    if (
        not isinstance(data, dict)
        or not isinstance(data.get("data"), list)  # pyright: ignore[reportUnknownMemberType]
        or not isinstance(data.get("meta"), dict)  # pyright: ignore[reportUnknownMemberType]
    ):
        raise NoheadError(f"The API's response could not be read (HTTP {response.status_code})")
    return cast("dict[str, Any]", data)


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
    if not settings.warnings:
        return
    if response.headers.get("deprecation") and first_warning(f"deprecation:{operation}"):
        sunset = response.headers.get("sunset")
        link = response.headers.get("link", "").partition("<")[2].partition(">")[0]
        message = f"{operation} is deprecated"
        if sunset:
            message += f" and will be removed after {sunset}"
        if link:
            message += f". See {link}"
        _warnings.warn(message, NoheadWarning, stacklevel=_outside_the_sdk())
    usage = response.headers.get("nohead-usage-warning")
    if usage and first_warning("usage"):
        _warnings.warn(f"Over a plan limit: {usage}", NoheadWarning, stacklevel=_outside_the_sdk())
