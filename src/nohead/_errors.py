"""The exceptions the SDK raises. Every one is a NoheadError."""

from __future__ import annotations

import re
import time
from datetime import UTC, datetime
from typing import Any, cast

import httpx

from .models import ErrorDetail


class NoheadError(Exception):
    """Base of every exception the SDK raises."""


class APIError(NoheadError):
    """The API answered with an error status. Subclasses follow the error `type`."""

    status: int
    """The HTTP status."""
    type: str | None
    """The error `type`, e.g. `validation_error`; None if the body had none."""
    message: str
    request_id: str | None
    """The request's ID (`req_...`), for support requests and logs."""
    details: list[ErrorDetail]
    """Field-level details, e.g. a `required` field."""
    headers: httpx.Headers
    body: Any
    """The parsed response body, or its text when it was not JSON."""

    def __init__(
        self,
        status: int,
        body: Any,
        headers: httpx.Headers,
        *,
        type: str | None = None,
        message: str | None = None,
    ) -> None:
        error = _envelope(body)
        self.status = status
        self.type = type or error.get("type")
        self.message = message or error.get("message") or f"Request failed with status {status}"
        self.request_id = error.get("request_id") or headers.get("x-request-id")
        raw_details: list[Any] = error.get("details") or []
        self.details = [_detail(d) for d in raw_details]
        self.headers = headers
        self.body = body
        super().__init__(self.message)

    def __str__(self) -> str:
        suffix = f" (request {self.request_id})" if self.request_id else ""
        return f"{self.status} {self.type or 'error'}: {self.message}{suffix}"


class InvalidRequestError(APIError):
    pass


class AuthenticationError(APIError):
    pass


class PlanLimitExceededError(APIError):
    pass


class AuthorizationError(APIError):
    pass


class NotFoundError(APIError):
    pass


class ConflictError(APIError):
    pass


class PreconditionFailedError(APIError):
    """An `if_match` revision was not the current one: reload and try again."""

    @property
    def current_revision(self) -> int | None:
        """The resource's current revision, when the API reports it."""
        for detail in self.details:
            if detail.code == "revision_mismatch":
                return detail.current_revision
        return None


class ValidationError(APIError):
    pass


class RateLimitError(APIError):
    @property
    def retry_after(self) -> float | None:
        """Seconds to wait before retrying, from `Retry-After`."""
        return retry_after_seconds(self.headers)


class InternalServerError(APIError):
    pass


class ServiceUnavailableError(APIError):
    pass


class APIConnectionError(NoheadError):
    """The request never got a response: DNS, TLS, a reset connection."""


class APITimeoutError(APIConnectionError):
    """An attempt took longer than the `timeout` option."""


class UploadError(NoheadError):
    """A presigned upload to storage failed (`assets.upload`)."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status
        """Storage's HTTP status, when it answered."""


class WebhookVerificationError(NoheadError):
    """A webhook request's signature or timestamp did not check out."""


_CLASSES: dict[str, type[APIError]] = {
    "invalid_request": InvalidRequestError,
    "authentication_error": AuthenticationError,
    "plan_limit_exceeded": PlanLimitExceededError,
    "authorization_error": AuthorizationError,
    "not_found": NotFoundError,
    "conflict": ConflictError,
    "precondition_failed": PreconditionFailedError,
    "validation_error": ValidationError,
    "rate_limited": RateLimitError,
    "internal_error": InternalServerError,
    "service_unavailable": ServiceUnavailableError,
}


def api_error(status: int, body: Any, headers: httpx.Headers) -> APIError:
    """The error for a response, by its `type`, or by status when it has none."""
    if 300 <= status < 400:
        # The API never redirects: a base URL that does (http:// to https://, a moved
        # host) would resend the request, its key included, somewhere else.
        location = headers.get("location")
        to = f" to {location}" if location else ""
        return APIError(
            status,
            body,
            headers,
            type="redirect",
            message=f"The API answered with a redirect{to}; check the base URL",
        )
    cls = _CLASSES.get(_envelope(body).get("type") or "")
    if cls is None:
        if status == 503:
            cls = ServiceUnavailableError
        elif status >= 500:
            cls = InternalServerError
        else:
            cls = APIError
    return cls(status, body, headers)


def retry_after_seconds(headers: httpx.Headers) -> float | None:
    """`Retry-After` in seconds: a number of seconds (`5`, `1.5`), or an HTTP date.
    None for anything else (`-1`, `1e3`, `inf`, an ISO 8601 date)."""
    value = (headers.get("retry-after") or "").strip()
    if re.fullmatch(r"[0-9]+(\.[0-9]+)?", value):
        return float(value)
    at = _http_date(value)
    return None if at is None else max(0.0, at.timestamp() - time.time())


_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_MONTH = "(?P<month>" + "|".join(_MONTHS) + ")"
_DAY = "(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)"
_TIME = "(?P<hour>[0-9]{2}):(?P<minute>[0-9]{2}):(?P<second>[0-9]{2})"
_HTTP_DATES = [
    # IMF-fixdate: Sun, 06 Nov 1994 08:49:37 GMT
    re.compile(f"{_DAY}, (?P<day>[0-9]{{2}}) {_MONTH} (?P<year>[0-9]{{4}}) {_TIME} GMT"),
    # RFC 850: Sunday, 06-Nov-94 08:49:37 GMT
    re.compile(
        "(?:Mon|Tues|Wednes|Thurs|Fri|Satur|Sun)day, "
        f"(?P<day>[0-9]{{2}})-{_MONTH}-(?P<year>[0-9]{{2}}) {_TIME} GMT"
    ),
    # asctime: Sun Nov  6 08:49:37 1994
    re.compile(f"{_DAY} {_MONTH} (?P<day>[0-9 ][0-9]) {_TIME} (?P<year>[0-9]{{4}})"),
]


def _http_date(value: str) -> datetime | None:
    """An HTTP date in any of RFC 9110's three forms, all GMT; None for anything else."""
    for pattern in _HTTP_DATES:
        if match := pattern.fullmatch(value):
            year = int(match["year"])
            if len(match["year"]) == 2:
                # RFC 850's two-digit year: the latest one at most 50 years ahead.
                year += 2000 if year + 2000 <= datetime.now(UTC).year + 50 else 1900
            try:
                return datetime(
                    year,
                    _MONTHS.index(match["month"]) + 1,
                    int(match["day"]),
                    int(match["hour"]),
                    int(match["minute"]),
                    int(match["second"]),
                    tzinfo=UTC,
                )
            except ValueError:  # no such day or time (31 Feb, 25:00)
                return None
    return None


def _envelope(body: Any) -> dict[str, Any]:
    """The error envelope's fields that have the right type: a proxy or gateway
    in front of the API may answer with any JSON."""
    if not isinstance(body, dict):
        return {}
    error = cast("dict[str, Any]", body).get("error")
    if not isinstance(error, dict):
        return {}
    error = cast("dict[str, Any]", error)
    fields: dict[str, Any] = {
        name: value
        for name in ("type", "message", "request_id")
        if isinstance(value := error.get(name), str)
    }
    if isinstance(details := error.get("details"), list):
        fields["details"] = cast("list[Any]", details)
    return fields


def _detail(raw: Any) -> ErrorDetail:
    try:
        return ErrorDetail.model_validate(raw)
    except Exception:
        if not isinstance(raw, dict):
            return ErrorDetail.model_construct(code="unknown", message=str(raw))
        # What it says, unvalidated: a `code` such as `in_progress` still counts.
        fields: dict[str, Any] = {"code": "unknown", "message": "", **cast("dict[str, Any]", raw)}
        return ErrorDetail.model_construct(**fields)
