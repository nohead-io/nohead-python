from __future__ import annotations

import httpx
import pytest

from nohead import (
    APIError,
    AuthenticationError,
    InternalServerError,
    NotFoundError,
    PlanLimitExceededError,
    PreconditionFailedError,
    RateLimitError,
    ServiceUnavailableError,
    ValidationError,
)

from .conftest import api_error, make_sync


def failure(response: httpx.Response) -> APIError:
    nohead, _ = make_sync([response], max_retries=0)
    with pytest.raises(APIError) as caught:
        nohead.records.get("rec_1")
    return caught.value


@pytest.mark.parametrize(
    ("status", "type", "cls"),
    [
        (401, "authentication_error", AuthenticationError),
        (402, "plan_limit_exceeded", PlanLimitExceededError),
        (404, "not_found", NotFoundError),
        (412, "precondition_failed", PreconditionFailedError),
        (422, "validation_error", ValidationError),
        (429, "rate_limited", RateLimitError),
        (500, "internal_error", InternalServerError),
        (503, "service_unavailable", ServiceUnavailableError),
    ],
)
def test_maps_types_to_classes(status: int, type: str, cls: type[APIError]) -> None:
    error = failure(api_error(status, type))
    assert isinstance(error, cls)
    assert (error.status, error.type, error.request_id) == (status, type, "req_1")
    assert str(error) == f"{status} {type}: {type} message (request req_1)"


def test_details() -> None:
    detail = {"field": "title", "code": "required", "message": "Title is required"}
    error = failure(api_error(422, "validation_error", details=[detail]))
    assert error.details[0].field == "title"
    assert error.details[0].code == "required"


def test_current_revision() -> None:
    detail = {
        "code": "revision_mismatch",
        "message": "Current revision is 7",
        "current_revision": 7,
    }
    error = failure(api_error(412, "precondition_failed", details=[detail]))
    assert isinstance(error, PreconditionFailedError)
    assert error.current_revision == 7


def test_retry_after() -> None:
    error = failure(api_error(429, "rate_limited", {"retry-after": "30"}))
    assert isinstance(error, RateLimitError)
    assert error.retry_after == 30


def test_bodies_that_are_not_api_errors() -> None:
    html = httpx.Response(502, text="<html>Bad gateway</html>", headers={"x-request-id": "req_9"})
    error = failure(html)
    assert isinstance(error, InternalServerError)
    assert error.body == "<html>Bad gateway</html>"
    assert error.request_id == "req_9"


def test_unknown_types_stay_api_errors() -> None:
    error = failure(api_error(418, "teapot_error"))
    assert type(error) is APIError
