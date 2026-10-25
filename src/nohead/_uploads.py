"""Reading files for assets.upload."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import IO, TypeAlias

from ._errors import UploadError

Uploadable: TypeAlias = bytes | bytearray | memoryview | str | os.PathLike[str] | IO[bytes]
"""What assets.upload accepts: bytes, a path, or a file opened in binary mode."""

CHUNK = 1024 * 1024

CONTENT_TYPES = {
    ".avif": "image/avif",
    ".gif": "image/gif",
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".webp": "image/webp",
    ".pdf": "application/pdf",
    ".json": "application/json",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".csv": "text/csv",
    ".mp3": "audio/mpeg",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".zip": "application/zip",
}
"""Common files' types by extension, as the other SDKs guess them: the same on every
platform and Python version, unlike `mimetypes`."""


@dataclass
class UploadSource:
    filename: str
    content_type: str
    byte_size: int
    data: bytes | None
    file: IO[bytes] | None
    start: int
    owned: bool

    @property
    def replayable(self) -> bool:
        """Whether the bytes can be sent again (for retries)."""
        return self.data is not None or (self.file is not None and self.file.seekable())

    def chunks(self) -> Iterator[bytes]:
        if self.data is not None:
            yield self.data
            return
        assert self.file is not None
        if self.file.seekable():
            self.file.seek(self.start)
        while chunk := self.file.read(CHUNK):
            yield chunk

    def close(self) -> None:
        if self.owned and self.file is not None:
            self.file.close()


def open_upload(
    file: Uploadable,
    filename: str | None,
    content_type: str | None,
    byte_size: int | None,
) -> UploadSource:
    data: bytes | None = None
    handle: IO[bytes] | None = None
    owned = False
    if isinstance(file, bytes | bytearray | memoryview):
        data = bytes(file)
        name = filename or "upload"
        size = len(data)
    elif isinstance(file, str | os.PathLike):
        path = Path(file)
        handle = path.open("rb")
        owned = True
        name = filename or path.name
        size = path.stat().st_size
    else:
        handle = file
        name = filename or os.path.basename(str(getattr(file, "name", "") or "")) or "upload"
        size = byte_size if byte_size is not None else _remaining(file)
        if size is None:
            raise UploadError("Uploading a stream that cannot seek needs byte_size")
    if byte_size is not None:
        size = byte_size
    guessed = CONTENT_TYPES.get(os.path.splitext(name)[1].lower(), "application/octet-stream")
    start = handle.tell() if handle is not None and handle.seekable() else 0
    return UploadSource(
        filename=name,
        content_type=content_type or guessed,
        byte_size=size,
        data=data,
        file=handle,
        start=start,
        owned=owned,
    )


def _remaining(file: IO[bytes]) -> int | None:
    """The bytes from here to the end, or None when the file can't seek (a pipe or a
    socket, whose size `fstat` doesn't know)."""
    try:
        if not file.seekable():
            return None
        here = file.tell()
        end = file.seek(0, os.SEEK_END)
        file.seek(here)
        return end - here
    except (OSError, ValueError):
        return None


def iter_file(source: UploadSource) -> Iterator[bytes]:
    yield from source.chunks()


async def aiter_file(source: UploadSource) -> AsyncIterator[bytes]:
    # File reads block briefly; asset files are small enough for that.
    for chunk in source.chunks():
        yield chunk
