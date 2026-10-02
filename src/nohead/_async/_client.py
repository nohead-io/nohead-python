# pyright: reportPrivateUsage=false
"""The HTTP core of the async client: requests, retries, errors and pages.

src/nohead/_sync is generated from this package by scripts/unasync.py: edit
the async code and run `uv run python scripts/unasync.py`.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any, TypeVar

import httpx

from .. import _base
from .._errors import APIConnectionError, APITimeoutError, NoheadError, api_error
from .._generated.operations import OPERATIONS
from .._pagination import AsyncPage, AsyncPaginator, start_async_pages
from .._uploads import UploadSource, aiter_file
from ..models import ListMeta, Principal
from ..types import IfMatch

T = TypeVar("T")
M = TypeVar("M")


class AsyncAPIClient:
    def __init__(self, settings: _base.Settings, http: httpx.AsyncClient | None) -> None:
        self.settings = settings
        self.http = http or httpx.AsyncClient()
        self.owns_http = http is None
        self._project_id = settings.project_id

    def copy(self, settings: _base.Settings) -> AsyncAPIClient:
        """The same connection pool and project, other settings."""
        client = AsyncAPIClient(settings, self.http)
        client.owns_http = False
        client._project_id = settings.project_id or self._project_id
        return client

    async def close(self) -> None:
        if self.owns_http:
            await self.http.aclose()

    async def project_id(self) -> str:
        """The API key's project, from `GET /v1/me` the first time."""
        if self._project_id is None:
            me = await self.request("me_get", cast=Principal)
            if me.api_key is None:
                raise NoheadError("The credentials are not a project API key")
            self._project_id = me.api_key.project_id
        return self._project_id

    async def request(
        self,
        operation: str,
        *,
        cast: type[T] | Any,
        path: Mapping[str, str | int] | None = None,
        query: Mapping[str, Any] | None = None,
        body: Any = None,
        idempotency_key: str | None = None,
        change_note: str | None = None,
        if_match: IfMatch | None = None,
    ) -> T:
        data = await self.send(
            operation,
            path=path,
            query=query,
            body=body,
            idempotency_key=idempotency_key,
            change_note=change_note,
            if_match=if_match,
        )
        return _base.validate(cast, data)

    def paginate(
        self,
        operation: str,
        *,
        item: type[T],
        meta: type[M] = ListMeta,
        path: Mapping[str, str | int] | None = None,
        query: Mapping[str, Any] | None = None,
    ) -> AsyncPaginator[T, Any]:
        """A list operation as pages of `item`."""
        params = dict(query or {})

        async def fetch(cursor: str | None) -> AsyncPage[T, Any]:
            data = await self.send(operation, path=path, query={**params, "cursor": cursor})
            items: list[T] = [_base.validate(item, raw) for raw in data["data"]]
            return AsyncPage(items, _base.validate(meta, data["meta"]), fetch)

        return start_async_pages(fetch, params.pop("cursor", None))

    async def send(
        self,
        operation: str,
        *,
        path: Mapping[str, str | int] | None = None,
        query: Mapping[str, Any] | None = None,
        body: Any = None,
        idempotency_key: str | None = None,
        change_note: str | None = None,
        if_match: IfMatch | None = None,
    ) -> Any:
        """Sends one operation, retrying as the README describes; returns the JSON."""
        method, template = OPERATIONS[operation]
        values = dict(path or {})
        if "{project_id}" in template and "project_id" not in values:
            values["project_id"] = await self.project_id()
        settings = self.settings
        url = _base.url(settings, template, values)
        headers = _base.headers(
            settings,
            method,
            has_body=body is not None,
            idempotency_key=idempotency_key,
            change_note=change_note,
            if_match=if_match,
        )
        content = None if body is None else _base.encode(body)
        params = _base.query(query)

        attempt = 0
        while True:
            try:
                response = await self.http.request(
                    method,
                    url,
                    params=params,
                    headers=headers,
                    content=content,
                    timeout=settings.timeout,
                )
            except httpx.TransportError as error:
                failure = _connection_error(error, settings.timeout, url)
                if attempt >= settings.max_retries:
                    raise failure from error
                await asyncio.sleep(_base.backoff(attempt))
                attempt += 1
                continue

            _base.warn(settings, operation, response)
            if response.is_success:
                return _base.parse(response)
            error = api_error(response.status_code, _base.parse(response), response.headers)
            delay = _base.retry_delay(error, attempt, settings.max_retries)
            if delay is None:
                raise error
            await asyncio.sleep(delay)
            attempt += 1

    async def put_upload(
        self, url: str, method: str, headers: Mapping[str, str], source: UploadSource
    ) -> httpx.Response:
        """Sends a file to a presigned storage URL (no API credentials)."""
        settings = self.settings
        retries = settings.max_retries if source.replayable else 0
        attempt = 0
        while True:
            try:
                response = await self.http.request(
                    method,
                    url,
                    headers={**headers, "Content-Length": str(source.byte_size)},
                    content=aiter_file(source),
                    timeout=settings.timeout,
                )
                if response.status_code not in _base.RETRYABLE_STATUSES or attempt >= retries:
                    return response
            except httpx.TransportError as error:
                if attempt >= retries:
                    raise _connection_error(error, settings.timeout, url) from error
            await asyncio.sleep(_base.backoff(attempt))
            attempt += 1


def _connection_error(error: httpx.TransportError, timeout: float, url: str) -> NoheadError:
    host = httpx.URL(url).host
    if isinstance(error, httpx.TimeoutException):
        return APITimeoutError(f"The request to {host} timed out after {timeout} s")
    return APIConnectionError(f"Could not reach {host}: {error}")
