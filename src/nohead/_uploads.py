"""Reading files for assets.upload."""

from __future__ import annotations

import mimetypes
import os
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import IO, TypeAlias

from ._errors import UploadError

Uploadable: TypeAlias = bytes | bytearray | memoryview | str | os.PathLike[str] | IO[bytes]
"""What assets.upload accepts: bytes, a path, or a file opened in binary mode."""

CHUNK = 1024 * 1024


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
    guessed = mimetypes.guess_type(name)[0]
    start = handle.tell() if handle is not None and handle.seekable() else 0
    return UploadSource(
        filename=name,
        content_type=content_type or guessed or "application/octet-stream",
        byte_size=size,
        data=data,
        file=handle,
        start=start,
        owned=owned,
    )


def _remaining(file: IO[bytes]) -> int | None:
    try:
        if file.seekable():
            here = file.tell()
            end = file.seek(0, os.SEEK_END)
            file.seek(here)
            return end - here
        return os.fstat(file.fileno()).st_size
    except (OSError, ValueError):
        return None


def iter_file(source: UploadSource) -> Iterator[bytes]:
    yield from source.chunks()


async def aiter_file(source: UploadSource) -> AsyncIterator[bytes]:
    # File reads block briefly; asset files are small enough for that.
    for chunk in source.chunks():
        yield chunk
