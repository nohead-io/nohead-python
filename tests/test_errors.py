"""API errors, with each client (the `make` fixture)."""

from __future__ import annotations

import httpx
import pytest

from nohead import (
    APIError,
    AuthenticationError,
    AuthorizationError,
    ConflictError,
    InternalServerError,
    InvalidRequestError,
    NotFoundError,
    PlanLimitExceededError,
    PreconditionFailedError,
    RateLimitError,
    ServiceUnavailableError,
    ValidationError,
)

from .conftest import Make, api_error, raw, resolve
from .spec import SPEC


async def failure(make: Make, response: httpx.Response) -> APIError:
    nohead, _ = make([response], max_retries=0)
    with pytest.raises(APIError) as caught:
        await resolve(nohead.records.get("rec_1"))
    return caught.value


# The class and usual status of each error type: a type the contract adds fails
# test_maps_types_to_classes until it is here (and has a class).
CLASSES: dict[str, tuple[type[APIError], int]] = {
    "invalid_request": (InvalidRequestError, 400),
    "authentication_error": (AuthenticationError, 401),
    "plan_limit_exceeded": (PlanLimitExceededError, 402),
    "authorization_error": (AuthorizationError, 403),
    "not_found": (NotFoundError, 404),
    "conflict": (ConflictError, 409),
    "precondition_failed": (PreconditionFailedError, 412),
    "validation_error": (ValidationError, 422),
    "rate_limited": (RateLimitError, 429),
    "internal_error": (InternalServerError, 500),
    "service_unavailable": (ServiceUnavailableError, 503),
}
ERROR_TYPES: list[str] = SPEC["components"]["schemas"]["ErrorType"]["enum"]


def test_knows_only_the_contracts_error_types() -> None:
    assert sorted(CLASSES) == sorted(ERROR_TYPES)
    assert len({cls for cls, _ in CLASSES.values()}) == len(CLASSES), "one class per type"


@pytest.mark.parametrize("error_type", ERROR_TYPES)
async def test_maps_types_to_classes(make: Make, error_type: str) -> None:
    assert error_type in CLASSES, f"No class for the contract's error type {error_type}"
    cls, status = CLASSES[error_type]
    error = await failure(make, api_error(status, error_type, {"x-a": "b"}))
    assert type(error) is cls
    assert error.headers["x-a"] == "b"
    assert (error.status, error.type, error.request_id) == (status, error_type, "req_1")
    assert str(error) == f"{status} {error_type}: {error_type} message (request req_1)"


async def test_details(make: Make) -> None:
    detail = {"field": "title", "code": "required", "message": "Title is required"}
    error = await failure(make, api_error(422, "validation_error", details=[detail]))
    assert error.details[0].field == "title"
    assert error.details[0].code == "required"


async def test_details_that_do_not_match_keep_what_they_say(make: Make) -> None:
    detail = {"code": "in_progress", "message": None, "retry": "soon"}
    error = await failure(make, raw(api_error(409, "conflict", details=[detail, "odd"])))
    assert (error.details[0].code, error.details[0].model_extra) == (
        "in_progress",
        {"retry": "soon"},
    )
    assert (error.details[1].code, error.details[1].message) == ("unknown", "odd")


async def test_current_revision(make: Make) -> None:
    detail = {
        "code": "revision_mismatch",
        "message": "Current revision is 7",
        "current_revision": 7,
    }
    error = await failure(make, api_error(412, "precondition_failed", details=[detail]))
    assert isinstance(error, PreconditionFailedError)
    assert error.current_revision == 7


async def test_retry_after(make: Make) -> None:
    error = await failure(make, api_error(429, "rate_limited", {"retry-after": "30"}))
    assert isinstance(error, RateLimitError)
    assert error.retry_after == 30


async def test_bodies_that_are_not_api_errors(make: Make) -> None:
    html = httpx.Response(502, text="<html>Bad gateway</html>", headers={"x-request-id": "req_9"})
    error = await failure(make, raw(html))
    assert isinstance(error, InternalServerError)
    assert error.body == "<html>Bad gateway</html>"
    assert error.request_id == "req_9"


async def test_fields_of_the_wrong_type(make: Make) -> None:
    # A gateway's JSON that looks like an envelope but is not one.
    body = {"error": {"type": ["x"], "message": {"text": "x"}, "request_id": 7, "details": "none"}}
    response = httpx.Response(502, json=body, headers={"x-request-id": "req_9"})
    error = await failure(make, raw(response))
    assert isinstance(error, InternalServerError)
    assert (error.type, error.message) == (None, "Request failed with status 502")
    assert (error.request_id, error.details) == ("req_9", [])


async def test_unknown_types_stay_api_errors(make: Make) -> None:
    error = await failure(make, raw(api_error(418, "teapot_error")))
    assert type(error) is APIError
