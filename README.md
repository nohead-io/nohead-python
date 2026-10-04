# Nohead Python SDK

The official Python client for the [Nohead](https://nohead.io) API, sync and async: typed models, pagination you can loop over, retries that are safe for writes, one-call uploads and webhook verification.

```python
from nohead import Nohead

nohead = Nohead()  # reads NOHEAD_API_KEY

for post in nohead.records.list("posts", filter={"status": "published"}):
    print(post.data["title"])
```

> **Status:** 0.x, not yet published to PyPI. Until it is, install from GitHub: `pip install git+https://github.com/nohead-io/nohead-python`.

## Contents

- [Installation](#installation)
- [Configuration](#configuration)
- [Async](#async)
- [Records](#records)
- [Pagination](#pagination)
- [Errors](#errors)
- [Retries and idempotency](#retries-and-idempotency)
- [Concurrency](#concurrency)
- [Assets](#assets)
- [Search](#search)
- [Schema](#schema)
- [Webhooks](#webhooks)
- [Types and models](#types-and-models)
- [Reference](#reference)
- [Development](#development)

## Installation

```bash
pip install nohead
```

It needs Python 3.11 or newer. Its dependencies are httpx and Pydantic 2. Use it on servers: API keys are secrets.

## Configuration

```python
nohead = Nohead(
    api_key=os.environ["NOHEAD_API_KEY"],  # default: NOHEAD_API_KEY
    base_url="https://api.nohead.io",  # default: NOHEAD_API_URL, else production
)
```

| Option | Default | |
|---|---|---|
| `api_key` | `NOHEAD_API_KEY` | A project API key (`sk_live_...`). Required. |
| `base_url` | `NOHEAD_API_URL`, else `https://api.nohead.io` | |
| `project_id` | the key's project | Looked up once with `GET /v1/me` when omitted. |
| `max_retries` | `2` | See [retries](#retries-and-idempotency). |
| `timeout` | `60.0` | Seconds per attempt. |
| `headers` | none | Added to every request. |
| `warnings` | `True` | Warns (`NoheadWarning`) about deprecated operations and plan usage, once each. |
| `http_client` | a new `httpx.Client` | Bring your own for proxies or custom transports. |

API keys belong to a project, so methods like `collections.list()` need no project ID. Collections can be named by ID or slug everywhere.

Close the client when you're done with it, or use it as a context manager: `with Nohead() as nohead: ...`.

`nohead.with_options(timeout=5, max_retries=0)` returns a client with other settings that shares the same connections.

## Async

`AsyncNohead` has the same methods; await them, and loop over lists with `async for`:

```python
from nohead import AsyncNohead

async with AsyncNohead() as nohead:
    post = await nohead.records.get("rec_01J9...")
    async for record in nohead.records.list("posts"):
        print(record.data["title"])
```

## Records

```python
draft = nohead.records.create("posts", data={"title": "Hello", "author": "rec_01J9..."})
post = nohead.records.get(draft.id, expand=["author"])
nohead.records.update(post.id, data={"title": "Hello again"})  # None clears a field
nohead.records.publish(post.id)
nohead.records.schedule(post.id, unpublish_at=datetime(2027, 1, 1, tzinfo=UTC))
nohead.records.delete(post.id)  # soft delete; records.restore() undoes it
```

Methods return models and raise on failure. Field values are in `record.data`, a dict keyed by field API key.

**More:**

- `count`, and `bulk` (up to 100 records at once)
- `diff(record, from_revision, to_revision)`
- `revisions.list`, `revisions.get` and `revisions.revert` (with `dry_run=True` for a preview)

## Pagination

List methods return the first page, which you can also loop over:

```python
# Every record, fetching pages as needed
for record in nohead.records.list("posts"):
    ...

# One page at a time
page = nohead.records.list("posts", limit=100)
page.data  # this page's records
page.meta  # next_cursor, has_more
while page.has_next_page():
    page = page.get_next_page()

# Resume from a saved cursor
nohead.records.list("posts", cursor=saved_cursor)
```

With `AsyncNohead`, `await nohead.records.list(...)` gives the first page and `async for` walks them all.

Filters are equality filters (for fields with several values: "contains"), and accept strings, numbers, booleans and datetimes:

```python
nohead.records.list(
    "posts",
    filter={"status": "published", "featured": True, "author": "rec_01J9..."},
    sort="-published_at",
    expand=["author", "tags"],
)
```

## Errors

Every exception is a `NoheadError`. API errors are `APIError`s with `status`, `type`, `message`, `request_id`, `details` and `headers`, in a class per type:

| Class | Status |
|---|---|
| `InvalidRequestError` | 400 |
| `AuthenticationError` | 401 |
| `PlanLimitExceededError` | 402 |
| `AuthorizationError` | 403 |
| `NotFoundError` | 404 |
| `ConflictError` | 409 |
| `PreconditionFailedError` | 412 (`current_revision`) |
| `ValidationError` | 422 |
| `RateLimitError` | 429 (`retry_after`) |
| `InternalServerError` | 500 and other 5xx |
| `ServiceUnavailableError` | 503 |

Other errors:

- `APIConnectionError`, and `APITimeoutError`, which is a kind of `APIConnectionError`
- `UploadError`
- `WebhookVerificationError`

```python
from nohead import ValidationError

try:
    nohead.records.create("posts", data={})
except ValidationError as error:
    for detail in error.details:
        print(detail.field, detail.code, detail.message)
```

## Retries and idempotency

Failed requests are retried twice by default (`max_retries`), with exponential backoff:

- what's retried: connection errors, timeouts, 429, 500, 502, 503, 504, and a 409 for a request that is still running
- `Retry-After` is honored up to 60 seconds; a longer one raises `RateLimitError` straight away

Every write gets an `Idempotency-Key` that stays the same across its retries, so a retry after a lost response never writes twice. To make a write safe across your own retries (a job that may run twice), pass a key:

```python
nohead.records.create("posts", data=data, idempotency_key=f"import-{row.id}")
```

Writes also take `change_note`, a reason shown in history.

## Concurrency

Pass the revision you read to make sure nobody changed the record since:

```python
from nohead import PreconditionFailedError

post = nohead.records.get(record_id)
try:
    nohead.records.update(record_id, data={"title": title}, if_match=post)
except PreconditionFailedError as error:
    ...  # changed since (now at error.current_revision): reload, and merge or ask
```

`if_match` takes a record or a revision number, on `update`, `delete`, `publish`, `unpublish` and `revisions.revert`.

## Assets

```python
asset = nohead.assets.upload("cover.jpg")
nohead.records.update(record_id, data={"cover": asset.id})

url = nohead.assets.image_url(asset.id, width=1200, format="webp").url
```

**What `upload` accepts:** a path, bytes, or a file opened in binary mode.

**What it does:**

1. Creates the upload.
2. Sends the bytes straight to storage.
3. Completes the upload, which checks the file, and returns the `ready` asset.

**Errors:** `UploadError` if storage refuses the bytes; `ValidationError` if the file fails the checks.

**Uploading from a browser:** create the upload on your server with `create_upload`, `PUT` the file from the browser, then `complete` it.

## Search

```python
# One collection
for hit in nohead.records.search("posts", "content model"):
    ...

# Across the project
results = nohead.search("content model", collections=["posts", "pages"])
results.meta.total_estimate
```

Search needs `search_enabled` collections and the `search:read` scope. It pages through the first 1,000 hits.

## Schema

```python
nohead.collections.create(
    name="Posts",
    slug="posts",
    fields=[{"name": "Title", "api_key": "title", "type": "text", "required": True}],
)
nohead.fields.create("posts", name="Summary", api_key="summary", type="long_text")

# Changes that rewrite records go through a migration; preview first
preview = nohead.fields.migrate("fld_...", type="long_text", dry_run=True)
migration = nohead.fields.migrate("fld_...", type="long_text")
nohead.migrations.get(migration.id)
```

For schema as code, see the `nohead` CLI (`nohead schema pull/diff/push`).

## Webhooks

Verify a webhook request, then use its event:

```python
from nohead.webhooks import unwrap

# e.g. in a Flask view
event = unwrap(request.get_data(), request.headers, secret=os.environ["NOHEAD_WEBHOOK_SECRET"])
if event.type == "record.published" and event.record:
    rebuild(event.record.collection)
```

`unwrap` checks the signature and the timestamp (Standard Webhooks), and raises `WebhookVerificationError` if either is off. Pass the raw body: parsing and re-serializing JSON changes the bytes.

`event.data` is the payload. For convenience, `event.record`, `event.asset`, `event.collection`, `event.schema_change` and `event.webhook` parse its parts, and are None when the event has no such part.

It's also available as `nohead.webhooks.unwrap(...)` on a client. Events can arrive more than once, so deduplicate by the `webhook-id` header.

## Types and models

- **Responses:** Pydantic models, in `nohead.models`. The main ones (`Record`, `Collection`, `Field`, `Asset`, `Webhook`) are also importable from `nohead`.
- **They're lenient on purpose, because the API adds fields and values without notice:**
  - Fields the SDK doesn't know yet are kept, in `model_extra`.
  - Enums are plain strings.
  - A response that doesn't match the models at all is still returned, unvalidated, with a `NoheadWarning`, rather than raised.
- **Timestamps** are `datetime`s.
- **Request bodies** are typed with the TypedDicts in `nohead.params`, so a type checker catches a misspelled field.

## Reference

| Resource | Methods |
|---|---|
| `records` | `list`, `get`, `create`, `update`, `delete`, `restore`, `publish`, `unpublish`, `schedule`, `unschedule`, `count`, `bulk`, `diff`, `search` |
| `records.revisions` | `list`, `get`, `revert` |
| `search` | across the project |
| `collections` | `list`, `get`, `create`, `update`, `delete`, `restore`, `schema` |
| `collections.schema_changes` | `list`, `get` |
| `collections.search_index` | `get`, `rebuild` |
| `fields` | `list`, `create`, `update`, `delete`, `restore`, `reorder`, `remove_alias`, `migrate` |
| `migrations` | `list`, `get`, `cancel` |
| `assets` | `upload`, `create_upload`, `complete`, `list`, `get`, `delete`, `restore`, `image_url`, `download_url` |
| `webhooks` | `list`, `get`, `create`, `update`, `delete`, `rotate_secret`, `test`, `unwrap` |
| `webhooks.deliveries` | `list`, `get`, `retry` |
| `audit_events` | `list` |
| `feature_flags` | `list` |
| `me` | `get` |
| `health` | `check` |

The SDK covers every operation an API key can call. Organizations, projects, members and API keys are managed in the web app. The full API is documented at [docs.nohead.io](https://docs.nohead.io).

## Development

```bash
uv sync                                  # Python 3.11+ and the dev tools
uv run pytest                            # unit and contract tests, both clients
uv run ruff format . && uv run ruff check . && uv run pyright
uv run python scripts/generate.py        # after updating openapi.json
uv run python scripts/unasync.py         # after changing src/nohead/_async
uv run python scripts/samples.py         # after changing tests/calls.py (the docs' code samples)
```

**How the code is organized:**

- `openapi.json` is the API's published contract. `scripts/generate.py` derives three files from it:
  - `src/nohead/models.py`
  - `src/nohead/params.py`
  - the operation table, `src/nohead/_generated/operations.py`
- **The async client is the source.** `src/nohead/_async` is written by hand, and `scripts/unasync.py` generates the sync client in `src/nohead/_sync` from it. Edit only the async code.
- `tests/test_contract.py` calls every public method of both clients. It fails when an API-key operation in the contract has no method, or when a request doesn't match its operation.

The smoke test (`smoke/smoke.py`) runs the core flow against a real API, with both clients, using the built package. Nohead's own CI runs it on every API contract change.

```bash
uv build
NOHEAD_API_URL=http://localhost:3000 NOHEAD_API_KEY=sk_live_... \
  uv run --isolated --no-project --with dist/nohead-0.1.0-py3-none-any.whl python smoke/smoke.py
```

## Releasing

1. Bump the version in `pyproject.toml` and `src/nohead/_version.py`.
2. Add a section for it to `CHANGELOG.md` (`## 1.2.3`), which becomes the release's notes.
3. Merge to `main`. Its ruleset requires the **CI passed** check, so the commit goes through a pull request or a branch whose CI passed, and force pushes are refused.
4. Run the **SDK release** workflow in the Nohead API repository. It runs this commit's smoke test against the API and pushes the tag `v1.2.3`. Nobody else can push `v*` tags: a tag ruleset lets only that workflow's deploy key through.
5. The tag starts `.github/workflows/release.yml`. Its publishing job runs in the `release` environment, which only `v*` tags can use, and the registry's trusted publisher accepts only that environment. It checks the version and its notes, tests and builds, and publishes to PyPI through trusted publishing (no token, with attestations). Then it creates the GitHub release with the built files.

## License

MIT
