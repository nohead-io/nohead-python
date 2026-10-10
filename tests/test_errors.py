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

from .conftest import Make, api_error, resolve


async def failure(make: Make, response: httpx.Response) -> APIError:
    nohead, _ = make([response], max_retries=0)
    with pytest.raises(APIError) as caught:
        await resolve(nohead.records.get("rec_1"))
    return caught.value


@pytest.mark.parametrize(
    ("status", "type", "cls"),
    [
        (400, "invalid_request", InvalidRequestError),
        (401, "authentication_error", AuthenticationError),
        (402, "plan_limit_exceeded", PlanLimitExceededError),
        (403, "authorization_error", AuthorizationError),
        (404, "not_found", NotFoundError),
        (409, "conflict", ConflictError),
        (412, "precondition_failed", PreconditionFailedError),
        (422, "validation_error", ValidationError),
        (429, "rate_limited", RateLimitError),
        (500, "internal_error", InternalServerError),
        (503, "service_unavailable", ServiceUnavailableError),
    ],
)
async def test_maps_types_to_classes(
    make: Make, status: int, type: str, cls: type[APIError]
) -> None:
    error = await failure(make, api_error(status, type, {"x-a": "b"}))
    assert isinstance(error, cls)
    assert error.headers["x-a"] == "b"
    assert (error.status, error.type, error.request_id) == (status, type, "req_1")
    assert str(error) == f"{status} {type}: {type} message (request req_1)"


async def test_details(make: Make) -> None:
    detail = {"field": "title", "code": "required", "message": "Title is required"}
    error = await failure(make, api_error(422, "validation_error", details=[detail]))
    assert error.details[0].field == "title"
    assert error.details[0].code == "required"


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
    error = await failure(make, html)
    assert isinstance(error, InternalServerError)
    assert error.body == "<html>Bad gateway</html>"
    assert error.request_id == "req_9"


async def test_unknown_types_stay_api_errors(make: Make) -> None:
    error = await failure(make, api_error(418, "teapot_error"))
    assert type(error) is APIError
