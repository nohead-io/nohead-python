"""What each client actually sends and receives over a socket: a real HTTP server on
127.0.0.1, in a thread of the test process, instead of the mock transport. The mock
can't show the headers httpx adds, how it frames a body, or how its timeouts and
parser behave."""

from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import AsyncIterator, Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, cast
from urllib.parse import urlsplit

import httpx
import pytest

from nohead import APIConnectionError, APIError, APITimeoutError, AsyncNohead, Nohead

from .conftest import record, resolve
from .spec import example_of

TIMEOUT = 0.25
"""The clients' timeout here, in seconds: short, so the tests are fast."""


@dataclass
class Seen:
    """A request as it reached the server."""

    method: str
    path: str
    headers: dict[str, str]
    body: bytes


Route = Callable[["Handler"], None]


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    @property
    def local(self) -> LocalServer:
        return cast(LocalServer, self.server)

    def do_GET(self) -> None:
        self.local.dispatch(self)

    do_POST = do_PUT = do_GET

    def log_message(self, format: str, *args: Any) -> None:
        pass

    def read_body(self) -> bytes:
        """The request's body, also when it is chunked (which a test then refuses)."""
        if self.headers.get("transfer-encoding", "").lower() == "chunked":
            body = b""
            while size := int(self.rfile.readline().split(b";")[0], 16):
                body += self.rfile.read(size)
                self.rfile.readline()
            self.rfile.readline()
            return body
        return self.rfile.read(int(self.headers.get("content-length", 0)))

    def head(self, status: int, length: int, headers: dict[str, str] | None = None) -> None:
        self.send_response(status)
        for name, value in {"Content-Length": str(length), **(headers or {})}.items():
            self.send_header(name, value)
        self.end_headers()

    def json(self, status: int, body: Any) -> None:
        content = json.dumps(body).encode()
        self.head(status, len(content), {"Content-Type": "application/json"})
        self.wfile.write(content)


class LocalServer(ThreadingHTTPServer):
    """Answers each `routes[(method, path)]`, and records every request in `seen`."""

    daemon_threads = True

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), Handler)
        self.routes: dict[tuple[str, str], Route] = {}
        self.seen: list[Seen] = []
        self.release = threading.Event()
        """Set when the test ends: a route that stalls waits for it."""

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}"

    def dispatch(self, handler: Handler) -> None:
        path = urlsplit(handler.path).path
        body = handler.read_body()
        headers = {name.lower(): value for name, value in handler.headers.items()}
        self.seen.append(Seen(handler.command, path, headers, body))
        route = self.routes.get((handler.command, path))
        if route is None:
            handler.json(404, {"error": {"type": "not_found", "message": "No route"}})
        else:
            route(handler)

    def handle_error(self, request: Any, client_address: Any) -> None:
        # A client that gave up (a timeout) closes the socket under a route.
        pass


@pytest.fixture
def server() -> Iterator[LocalServer]:
    local = LocalServer()
    thread = threading.Thread(target=local.serve_forever, args=(0.01,), daemon=True)
    thread.start()
    yield local
    local.release.set()
    local.shutdown()
    local.server_close()


Connect = Callable[..., Any]


@pytest.fixture(params=["sync", "async"])
async def connect(request: pytest.FixtureRequest, server: LocalServer) -> AsyncIterator[Connect]:
    """Makes a Nohead or an AsyncNohead (the test runs with each) for the server, with
    its own HTTP client (or one that follows redirects); closes them after the test."""
    opened: list[Any] = []

    def make(*, follow_redirects: bool = False, **options: Any) -> Any:
        settings: dict[str, Any] = {
            "api_key": "nohead_sk_test",
            "base_url": server.url,
            "project_id": "prj_1",
            "timeout": TIMEOUT,
            **options,
        }
        if request.param == "sync":
            http: Any = httpx.Client(follow_redirects=True) if follow_redirects else None
            client: Any = Nohead(http_client=http, **settings)
        else:
            http = httpx.AsyncClient(follow_redirects=True) if follow_redirects else None
            client = AsyncNohead(http_client=http, **settings)
        opened.append((client, http))
        return client

    yield make
    for client, http in opened:
        await resolve(client.close())
        if http is not None:
            await resolve(http.aclose() if isinstance(http, httpx.AsyncClient) else http.close())


def asset(status: str, byte_size: int) -> dict[str, Any]:
    return example_of(
        "Asset",
        id="ast_1",
        project_id="prj_1",
        filename="notes.txt",
        content_type="text/plain",
        byte_size=byte_size,
        status=status,
    )


async def test_sends_a_stream_with_its_length_not_chunked(
    server: LocalServer, connect: Connect
) -> None:
    data = os.urandom(200_000)
    expires_at = (datetime.now(UTC) + timedelta(minutes=15)).isoformat()
    upload = {
        "method": "PUT",
        "url": f"{server.url}/storage/ast_1?signature=x",
        "headers": {"Content-Type": "text/plain"},
        "expires_at": expires_at,
    }
    server.routes = {
        ("POST", "/v1/projects/prj_1/assets"): lambda h: h.json(
            201, {**asset("pending", len(data)), "upload": upload}
        ),
        ("PUT", "/storage/ast_1"): lambda h: h.head(200, 0),
        ("POST", "/v1/assets/ast_1/complete"): lambda h: h.json(200, asset("ready", len(data))),
    }
    # A pipe can't seek or tell its size: the bytes reach storage as they are read.
    read, write = os.pipe()

    def feed() -> None:
        with open(write, "wb") as pipe:
            pipe.write(data)

    threading.Thread(target=feed, daemon=True).start()
    nohead = connect()
    with open(read, "rb") as stream:
        assert not stream.seekable()
        ready = await resolve(
            nohead.assets.upload(stream, filename="notes.txt", byte_size=len(data))
        )
    assert ready.status == "ready"
    assert [f"{s.method} {s.path}" for s in server.seen] == [
        "POST /v1/projects/prj_1/assets",
        "PUT /storage/ast_1",
        "POST /v1/assets/ast_1/complete",
    ]
    put = server.seen[1]
    assert put.headers["content-length"] == str(len(data))
    assert "transfer-encoding" not in put.headers
    assert put.headers["content-type"] == "text/plain"
    assert "authorization" not in put.headers
    assert put.body == data


def trickle(pieces: int, gap: float, stall: bool = False) -> Route:
    """A route that answers a record in `pieces`, `gap` seconds apart, or that stops
    halfway (until the test ends) when it `stall`s."""

    def route(handler: Handler) -> None:
        body = json.dumps(record("rec_1", title="Slow")).encode()
        handler.head(200, len(body), {"Content-Type": "application/json"})
        size = -(-len(body) // pieces)
        for start in range(0, len(body), size):
            if start:
                if stall and start >= len(body) // 2:
                    handler.local.release.wait(5)
                    return
                time.sleep(gap)
            handler.wfile.write(body[start : start + size])

    return route


async def test_the_timeout_is_for_no_progress_not_the_whole_response(
    server: LocalServer, connect: Connect
) -> None:
    # 8 gaps of 0.07 s: over twice the timeout in all, each well within it.
    server.routes = {("GET", "/v1/records/rec_1"): trickle(9, 0.07)}
    nohead = connect(max_retries=0)
    started = time.monotonic()
    got = await resolve(nohead.records.get("rec_1"))
    assert got.data == {"title": "Slow"}
    assert time.monotonic() - started > 2 * TIMEOUT


async def test_times_out_when_the_response_stalls(server: LocalServer, connect: Connect) -> None:
    server.routes = {("GET", "/v1/records/rec_1"): trickle(9, 0.0, stall=True)}
    nohead = connect(max_retries=0)
    with pytest.raises(APITimeoutError, match=rf"timed out after {TIMEOUT} s"):
        await resolve(nohead.records.get("rec_1"))
    assert len(server.seen) == 1


@pytest.mark.parametrize("status", [301, 302])
@pytest.mark.parametrize("follow_redirects", [False, True], ids=["default", "following"])
async def test_does_not_follow_a_redirect(
    server: LocalServer, connect: Connect, status: int, follow_redirects: bool
) -> None:
    def moved(handler: Handler) -> None:
        body = b"<html>Moved</html>"
        location = f"{server.url}/v1/records/rec_2"
        handler.head(status, len(body), {"Location": location, "Content-Type": "text/html"})
        handler.wfile.write(body)

    server.routes = {
        ("GET", "/v1/records/rec_1"): moved,
        ("GET", "/v1/records/rec_2"): lambda h: h.json(200, record("rec_2")),
    }
    nohead = connect(follow_redirects=follow_redirects)
    with pytest.raises(APIError) as caught:
        await resolve(nohead.records.get("rec_1"))
    assert type(caught.value) is APIError
    assert (caught.value.status, caught.value.type) == (status, "redirect")
    assert f"redirect to {server.url}/v1/records/rec_2" in str(caught.value)
    assert [s.path for s in server.seen] == ["/v1/records/rec_1"]


async def test_a_malformed_response_is_a_connection_error(
    server: LocalServer, connect: Connect
) -> None:
    def garbage(handler: Handler) -> None:
        handler.wfile.write(b"HTTP/1.1 two hundred OK\r\n\r\n")
        handler.close_connection = True

    server.routes = {("GET", "/v1/records/rec_1"): garbage}
    nohead = connect(max_retries=1)
    with pytest.raises(APIConnectionError, match=r"Could not reach 127\.0\.0\.1") as caught:
        await resolve(nohead.records.get("rec_1"))
    assert not isinstance(caught.value, APITimeoutError)
    assert isinstance(caught.value.__cause__, httpx.RemoteProtocolError)
    # Like a dropped connection, retried.
    assert len(server.seen) == 2
