"""assets.upload, with each client (the `make` fixture)."""

from __future__ import annotations

import io
from pathlib import Path

import httpx
import pytest

from nohead import UploadError, ValidationError

from .conftest import Make, api_error, json_response, resolve


def asset(status: str) -> dict[str, object]:
    return {
        "id": "ast_1",
        "object": "asset",
        "project_id": "prj_1",
        "filename": "a.png",
        "content_type": "image/png",
        "byte_size": 3,
        "width": None,
        "height": None,
        "status": status,
        "deleted": False,
        "preview_url": None,
        "uploaded_at": None,
        "created_at": "2026-10-02T12:00:00.000Z",
        "updated_at": "2026-10-02T12:00:00.000Z",
    }


CREATED = json_response(
    201,
    {
        "object": "asset_upload",
        "asset": asset("pending"),
        "upload": {
            "method": "PUT",
            "url": "https://storage.test/uploads/prj_1/ast_1?signature=x",
            "headers": {"Content-Type": "image/png"},
            "expires_at": "2026-10-02T13:00:00.000Z",
        },
    },
)
STORED = httpx.Response(200)
READY = json_response(200, asset("ready"))


async def test_uploads_a_path(make: Make, tmp_path: Path) -> None:
    file = tmp_path / "a.png"
    file.write_bytes(b"\x01\x02\x03")
    nohead, calls = make([CREATED, STORED, READY], timeout=9)
    ready = await resolve(nohead.assets.upload(file))
    assert ready.status == "ready"
    assert [f"{c.method} {c.url.host}{c.url.path}" for c in calls.calls] == [
        "POST api.test/v1/projects/prj_1/assets/uploads",
        "PUT storage.test/uploads/prj_1/ast_1",
        "POST api.test/v1/assets/ast_1/complete",
    ]
    assert calls.body(0) == {"filename": "a.png", "content_type": "image/png", "byte_size": 3}
    put = calls.calls[1]
    assert put.content == b"\x01\x02\x03"
    assert put.headers["content-length"] == "3"
    assert put.headers["content-type"] == "image/png"
    assert "authorization" not in put.headers
    assert put.extensions["timeout"]["read"] == 9


async def test_uses_an_idempotency_key_only_to_start_the_upload(make: Make) -> None:
    nohead, calls = make([CREATED, STORED, READY])
    await resolve(nohead.assets.upload(b"x", idempotency_key="k1"))
    keys = [c.headers.get("idempotency-key") for c in calls.calls]
    assert keys[0] == "k1"
    assert keys[2] and len(keys[2]) == 36


async def test_uploads_bytes_with_a_name(make: Make) -> None:
    nohead, calls = make([CREATED, STORED, READY])
    await resolve(nohead.assets.upload(b"0123456789", filename="data.bin"))
    assert calls.body(0) == {
        "filename": "data.bin",
        "content_type": "application/octet-stream",
        "byte_size": 10,
    }


async def test_uploads_a_file_object(make: Make) -> None:
    nohead, calls = make([CREATED, STORED, READY])
    await resolve(nohead.assets.upload(io.BytesIO(b"hello"), filename="hello.txt"))
    assert calls.body(0)["content_type"] == "text/plain"
    assert calls.calls[1].content == b"hello"


async def test_needs_byte_size_for_a_stream(make: Make) -> None:
    class Stream(io.BytesIO):
        def seekable(self) -> bool:
            return False

    nohead, _ = make([CREATED])
    with pytest.raises(UploadError):
        await resolve(nohead.assets.upload(Stream(b"hello")))


async def test_retries_the_bytes_on_a_server_error(make: Make) -> None:
    nohead, calls = make([CREATED, httpx.Response(503), STORED, READY])
    await resolve(nohead.assets.upload(b"x"))
    assert [f"{c.method} {c.url.host}" for c in calls.calls] == [
        "POST api.test",
        "PUT storage.test",
        "PUT storage.test",
        "POST api.test",
    ]
    assert calls.calls[2].content == b"x"


async def test_storage_refusing_the_bytes(make: Make) -> None:
    nohead, _ = make([CREATED, httpx.Response(403, text="denied")])
    with pytest.raises(UploadError) as caught:
        await resolve(nohead.assets.upload(b"x"))
    assert caught.value.status == 403


async def test_a_file_that_fails_the_checks(make: Make) -> None:
    nohead, _ = make([CREATED, STORED, api_error(422, "validation_error")], max_retries=0)
    with pytest.raises(ValidationError):
        await resolve(nohead.assets.upload(b"x"))
