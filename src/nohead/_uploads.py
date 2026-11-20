"""Reading files for assets.upload."""

from __future__ import annotations

import errno
import os
import stat
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import IO, TypeAlias, cast

from ._errors import UploadError

Uploadable: TypeAlias = bytes | bytearray | memoryview | str | os.PathLike[str] | IO[bytes]
"""What assets.upload accepts: bytes, a path, or a file opened in binary mode."""

CHUNK = 1024 * 1024


@dataclass
class UploadSource:
    filename: str
    content_type: str | None
    """The type given; None leaves it to the API, which types the file by its filename."""
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
        """The first `byte_size` bytes, the length the upload declared. Raises
        UploadError when the file ends sooner."""
        if self.data is not None:  # open_upload cut them to byte_size
            yield self.data
            return
        assert self.file is not None
        if self.file.seekable():
            self.file.seek(self.start)
        sent = 0
        while sent < self.byte_size:
            # A non-blocking raw stream returns None when it has nothing to read yet.
            chunk = cast("bytes | None", self.file.read(min(CHUNK, self.byte_size - sent)))
            if chunk is None:
                raise UploadError(
                    f"Could not upload {self.filename}: it is a non-blocking stream, "
                    "which can't be uploaded"
                )
            if not chunk:
                raise _too_short(self.filename, sent, self.byte_size)
            sent += len(chunk)
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
        name = filename or path.name
        info = path.stat()  # a missing path raises FileNotFoundError, as open() would
        if stat.S_ISDIR(info.st_mode):
            raise IsADirectoryError(errno.EISDIR, os.strerror(errno.EISDIR), str(path))
        # A pipe's or a device's size (/dev/stdin) is not what it holds.
        size = info.st_size if stat.S_ISREG(info.st_mode) else None
        if size is None and byte_size is None:
            raise UploadError(f"Uploading {path}, which is not a file, needs byte_size")
        handle = path.open("rb")
        owned = True
    else:
        handle = file
        name = filename or os.path.basename(str(getattr(file, "name", "") or "")) or "upload"
        size = _remaining(file)
    if byte_size is not None:
        # A file known to be shorter fails before the upload starts.
        if size is not None and size < byte_size:
            if owned and handle is not None:
                handle.close()
            raise _too_short(name, size, byte_size)
        size = byte_size
        if data is not None:
            data = data[:size]
    if size is None:
        raise UploadError("Uploading a stream whose size isn't known needs byte_size")
    start = handle.tell() if handle is not None and handle.seekable() else 0
    return UploadSource(
        filename=name,
        content_type=content_type or None,
        byte_size=size,
        data=data,
        file=handle,
        start=start,
        owned=owned,
    )


def _too_short(filename: str, size: int, byte_size: int) -> UploadError:
    return UploadError(
        f"Could not upload {filename}: it has {size} bytes, fewer than its byte_size ({byte_size})"
    )


def _remaining(file: IO[bytes]) -> int | None:
    """The bytes from here to the end, or None when the file can't seek (a pipe or a
    socket, whose size `fstat` doesn't know) or is a device (/dev/stdin), whose size
    isn't what it holds."""
    try:
        if not file.seekable() or not _regular(file):
            return None
        here = file.tell()
        end = file.seek(0, os.SEEK_END)
        file.seek(here)
        return end - here
    except (OSError, ValueError):
        return None


def _regular(file: IO[bytes]) -> bool:
    """Whether the file is a regular one, or has no descriptor (BytesIO) to say."""
    try:
        descriptor = file.fileno()
    except (AttributeError, OSError, ValueError):
        return True
    return stat.S_ISREG(os.fstat(descriptor).st_mode)


def iter_file(source: UploadSource) -> Iterator[bytes]:
    yield from source.chunks()


async def aiter_file(source: UploadSource) -> AsyncIterator[bytes]:
    # File reads block briefly; asset files are small enough for that.
    for chunk in source.chunks():
        yield chunk
