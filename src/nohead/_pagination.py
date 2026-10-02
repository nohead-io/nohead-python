"""Pages of lists, for the sync and the async client."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Generator, Iterator
from typing import Any, Generic, Protocol

from typing_extensions import TypeVar

from ._errors import NoheadError
from .models import ListMeta


class PageMeta(Protocol):
    @property
    def has_more(self) -> bool: ...
    @property
    def next_cursor(self) -> str | None: ...


T = TypeVar("T")
M = TypeVar("M", bound=PageMeta, default=ListMeta)


class Page(Generic[T, M]):
    """One page of a list. Iterating it walks every item from here on, fetching
    later pages as needed:

        for record in nohead.records.list("posts"): ...

        page = nohead.records.list("posts", limit=100)
        page.data, page.meta.next_cursor
        while page.has_next_page():
            page = page.get_next_page()
    """

    data: list[T]
    """The items on this page."""
    meta: M
    """`next_cursor` and `has_more` (and `total_estimate` for search)."""

    def __init__(self, data: list[T], meta: M, fetch: Callable[[str], Page[T, M]]) -> None:
        self.data = data
        self.meta = meta
        self._fetch = fetch

    def has_next_page(self) -> bool:
        return self.meta.has_more and self.meta.next_cursor is not None

    def get_next_page(self) -> Page[T, M]:
        """The next page; raises NoheadError when there is none."""
        if not self.has_next_page():
            raise NoheadError("There is no next page")
        return self._fetch(self.meta.next_cursor or "")

    def __iter__(self) -> Iterator[T]:
        page: Page[T, M] | None = self
        while page is not None:
            yield from page.data
            page = page.get_next_page() if page.has_next_page() else None

    def __repr__(self) -> str:
        return f"Page(data=[{len(self.data)} items], meta={self.meta!r})"


class AsyncPage(Generic[T, M]):
    """One page of a list (async). `async for` walks every item from here on."""

    data: list[T]
    meta: M

    def __init__(
        self, data: list[T], meta: M, fetch: Callable[[str], Awaitable[AsyncPage[T, M]]]
    ) -> None:
        self.data = data
        self.meta = meta
        self._fetch = fetch

    def has_next_page(self) -> bool:
        return self.meta.has_more and self.meta.next_cursor is not None

    async def get_next_page(self) -> AsyncPage[T, M]:
        if not self.has_next_page():
            raise NoheadError("There is no next page")
        return await self._fetch(self.meta.next_cursor or "")

    async def __aiter__(self) -> AsyncIterator[T]:
        page: AsyncPage[T, M] | None = self
        while page is not None:
            for item in page.data:
                yield item
            page = await page.get_next_page() if page.has_next_page() else None

    def __repr__(self) -> str:
        return f"AsyncPage(data=[{len(self.data)} items], meta={self.meta!r})"


class AsyncPaginator(Generic[T, M]):
    """What async list methods return. Awaiting it gives the first page;
    `async for` walks every item across pages:

        page = await nohead.records.list("posts")
        async for record in nohead.records.list("posts"): ...
    """

    def __init__(
        self, fetch: Callable[[str | None], Awaitable[AsyncPage[T, M]]], cursor: str | None
    ):
        self._fetch = fetch
        self._cursor = cursor

    def __await__(self) -> Generator[Any, None, AsyncPage[T, M]]:
        return self._fetch(self._cursor).__await__()

    async def __aiter__(self) -> AsyncIterator[T]:
        async for item in await self:
            yield item


def start_async_pages(
    fetch: Callable[[str | None], Awaitable[AsyncPage[T, M]]], cursor: str | None
) -> AsyncPaginator[T, M]:
    """Async lists fetch on await or iteration."""
    return AsyncPaginator(fetch, cursor)


def start_pages(fetch: Callable[[str | None], Page[T, M]], cursor: str | None) -> Page[T, M]:
    """Sync lists fetch their first page at once."""
    return fetch(cursor)
