from __future__ import annotations

from .._client import AsyncAPIClient


class AsyncResource:
    def __init__(self, client: AsyncAPIClient) -> None:
        self._client = client
