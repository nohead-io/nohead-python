# Nohead Python SDK

The official Python client for the [Nohead](https://nohead.io) API, sync and async: typed models, pagination you can loop over, retries that are safe for writes, one-call uploads and webhook verification.

```python
from nohead import Nohead

nohead = Nohead()  # reads NOHEAD_API_KEY

for post in nohead.records.list("posts", filter={"published_at": {"exists": True}}):
    print(post.data["title"])
```

> **Status:** 0.x until the Nohead API launches.

## Contents

- [Installation](#installation)
- [Configuration](#configuration)
- [Async](#async)
- [Records](#records)
- [Drafts](#drafts)
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
    api_key=os.environ["NOHEAD_API_KEY"],  # the default
    timeout=10.0,
    max_retries=3,
)
```

| Option | Default | |
|---|---|---|
| `api_key` | `NOHEAD_API_KEY` | A project API key (`nohead_sk_...`, or `nohead_pk_...` when published-only). Required. |
| `base_url` | `https://api.nohead.io` | For a proxy, or a mock server in tests. An `http` or `https` URL; anything else raises `NoheadError`. |
| `project_id` | the key's project | Looked up once with `GET /v1/me` when omitted (calls made at the same time share the lookup). |
| `max_retries` | `2` | See [retries](#retries-and-idempotency). |
| `timeout` | `60.0` | Seconds an attempt may go without progress: to connect, to send, to get the response, and between reads of it. A response that keeps arriving doesn't time out. |
| `headers` | none | Added to every request. They replace the SDK's own (`Authorization`, `User-Agent`...) whatever the case of their names, but not the ones it sets from a call's options (`Content-Type`, `Idempotency-Key`, `If-Match`, `Nohead-Change-Note`). |
| `warnings` | `True` | Warns (`NoheadWarning`) about deprecated operations and plan usage, once each. |
| `on_retry` | none | Called before each retry's wait, with a `RetryEvent`. See [retries](#retries-and-idempotency). |
| `http_client` | a new `httpx.Client` | Bring your own for proxies or custom transports. |

An empty string counts as not given: `api_key=""` reads `NOHEAD_API_KEY`, and so on.

API keys belong to a project, so methods like `collections.list()` need no project ID. Collections can be named by ID or slug everywhere.

Close the client when you're done with it, or use it as a context manager: `with Nohead() as nohead: ...`.

`nohead.with_options(timeout=5, max_retries=0)` returns a client with other settings that shares the same connections and project. It takes `timeout`, `max_retries`, `headers` (added to the client's) and `on_retry`.

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
created = nohead.records.create("posts", data={"title": "Hello", "author": "rec_01J9..."})
post = nohead.records.get(created.id, expand=["author"])
nohead.records.update(post.id, data={"title": "Hello again"})  # None clears a field
nohead.records.publish(post.id)
nohead.records.publication(post.id)  # since when, by whom, which revision
# The whole schedule: a time left out is cleared
nohead.records.schedule(post.id, unpublish_at=datetime(2027, 1, 1, tzinfo=UTC))
nohead.records.delete(post.id)  # soft delete; records.restore() undoes it
```

Methods return models and raise on failure. Field values are in `record.data`, a dict keyed by field API key.

**Upserts.** With `upsert_on`, the key of a `unique` field, `create` updates the record holding that value instead, if one exists, so a content sync can run again without duplicates: `nohead.records.create("products", data={"sku": "TEE-01", "title": "Tee"}, upsert_on="sku")`.

**More:**

- `count`, and `bulk` (up to 100 records at once, each succeeding or failing on its own: its `results` are `RecordBatchResultsSucceeded` or `RecordBatchResultsFailed`, by `status`)
- `diff(record, from_revision=1, to_revision=2)`
- `revisions.list` (`filter` by `operation`, `actor_id` or a `created_at` range), `revisions.get` and `revisions.revert` (with `dry_run=True` for a preview)
- a revision by its own ID, as webhooks and the activity log name it: `nohead.revisions.get("rev_...")`

## Drafts

A draft holds changes to a record until they are merged, now or at a set time, while the record keeps its current content: changes to review before they go live, or changes due later.

```python
draft = nohead.drafts.create(post.id, data={"title": "Hello, revised"})
nohead.drafts.update(draft.id, data={"summary": "..."}, if_match=draft)
preview = nohead.drafts.get(draft.id, expand=["author"])  # data as it would read
nohead.drafts.merge(draft.id)  # or drafts.schedule(draft.id, merge_at=...)
```

- A record has at most one draft; starting a second is a `ConflictError` (detail code `draft_exists`, with its `draft_id`).
- A merge changes content only: a live record stays live, an unpublished one unpublished. Publishing a live record with a pending draft is a `ConflictError` (`draft_pending`).
- `records.drafts(id)` lists a record's draft, and `drafts.list(collection)` a collection's.
- `drafts.discard` deletes one for good.

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

Filters take a value to equal, or operators: `eq`, `ne`, `gt`, `gte`, `lt`, `lte`, `in` (a list) and `exists`. They combine with AND. On fields with several values, equal means "contains". Values are strings, numbers, booleans, `datetime`s (for date fields with a time) and `date`s (for plain date fields, sent as `YYYY-MM-DD`); dates take `"today"` too, and dates with a time `"now"`. Lists sort by a field as well, with records that have no value last:

```python
nohead.records.list(
    "posts",
    filter={"published_at": {"exists": True}, "featured": True, "author": "rec_01J9..."},
    sort="-published_at",
    expand=["author", "tags"],
)

nohead.records.list(
    "products",
    filter={"price": {"lt": 50}, "category": {"in": ["shoes", "bags"]}, "cover": {"exists": True}},
    sort="price",
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

The API never redirects, so a redirect (a base URL that does, such as `http://` to `https://`) isn't followed: it raises an `APIError` whose `type` is `redirect`, such as `301 redirect: The API answered with a redirect to https://api.nohead.io/v1/records; check the base URL`.

Other errors:

- `APIConnectionError`, and `APITimeoutError`, which is a kind of `APIConnectionError`
- `UploadError`
- `WebhookVerificationError`
- `NoheadError` itself, for a list response that isn't a list (`The API's response could not be read (HTTP 200)`, from a proxy, say), and for a path value that is empty, `.` or `..`, before sending anything

Values that can't be sent raise Python's own errors before sending: `TypeError` for an `if_match` that isn't a revision number and has no `revision`, and `ValueError` for a `datetime` without a time zone, `nan` or an infinity.

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
- `Retry-After` is honored up to 60 seconds; a longer one raises `RateLimitError` straight away. It is a number of seconds (`5`, `1.5`) or an HTTP date; anything else is ignored, and the usual backoff applies

`on_retry` is called before each retry's wait, also for an upload's bytes, with a `RetryEvent`: the `attempt` (1 for the first retry), the `delay` in seconds, the `url`, and the `status` that failed (None when the connection did) and the `error` (an `APIError` or `APIConnectionError`; None for a status from storage):

```python
from nohead import Nohead, RetryEvent


def log_retry(retry: RetryEvent) -> None:
    log.warning("Retry %d in %.1f s: %s", retry.attempt, retry.delay, retry.error)


nohead = Nohead(on_retry=log_retry)
```

Every write gets an `Idempotency-Key` that stays the same across its retries, so a retry after a lost response never writes twice. To make a write safe across your own retries (a job that may run twice), pass a key:

```python
nohead.records.create("posts", data=data, idempotency_key=f"import-{row.id}")
```

Writes that change records or the schema also take `change_note`, a reason shown in history.

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

`if_match` takes a record, a revision number, or a mapping with a `revision` (`{"revision": 3}`), on the records' `update`, `delete`, `restore`, `publish`, `unpublish` and `revisions.revert`, and the drafts' `update`, `discard` and `merge` (with the draft's `revision`).

## Assets

```python
asset = nohead.assets.upload("cover.jpg")
nohead.records.update(record_id, data={"cover": asset.id})
```

**Images.** Image URLs are open: an image's `image_url` serves the whole image, and any of [imgproxy's processing options](https://docs.imgproxy.net/usage/processing) written into it transform it. `nohead.images.image_url` builds them without a request:

```python
from nohead.images import image_url

image_url(asset, width=1200, height=630, fit="cover", gravity="sm", format="webp")
image_url(asset.image_url, width=400, dpr=2, options=["bl:2"])
```

It takes an asset, as a model or a mapping (`{"image_url": ...}`), or its `image_url`.

Thumbnails: an image's `preview_url` fits in 640×640, as WebP.

**What `upload` accepts:** a path, bytes, or a file opened in binary mode.

**What it does:**

1. Creates the upload.
2. Sends the bytes straight to storage.
3. Completes the upload, which checks the file, and returns the `ready` asset.

**Errors:** `UploadError` if the bytes don't reach storage: it refuses them (`Storage refused the upload of photo.jpg (403)`, with its `status`), or it can't be reached or times out (`Could not upload photo.jpg: ...`, with the `APIConnectionError` or `APITimeoutError` as its `__cause__`). `ValidationError` if the file fails the checks.

**Resuming:** with an `idempotency_key`, running the same upload again resumes it: an asset that is already `ready` is returned without sending the bytes again. Once the upload's URL has expired (its `upload.expires_at`), it raises `UploadError`: start over with a new key.

**Renaming and alt text:** `update` changes an asset's `filename` and `alt` text, the default wherever the asset is used (`expand` returns it with the asset). The file itself never changes.

```python
nohead.assets.update(asset.id, alt="The spring menu, on a chalkboard")
```

**Deleting:** `usage` shows which records use an asset. `delete` keeps the file until its `purge_after`, during which `restore` undoes it; `purge` removes a deleted asset for good, now.

## Search

```python
# One collection
for hit in nohead.records.search("posts", "content model"):
    ...

# Across the project
results = nohead.search(
    "content model",
    collections=["posts", "pages"],
    filter={"published_at": {"exists": True}},
)
results.meta.total_estimate
```

Search needs the `search:read` scope and covers every collection the key can read, matching their `searchable` fields. It pages through the first 1,000 hits. For search straight from a site's browser, without the API, use a search token from the web app with Meilisearch's own clients or InstantSearch.

## Schema

```python
nohead.collections.create(
    name="Posts",
    slug="posts",
    fields=[{"name": "Title", "key": "title", "type": "text", "required": True}],
)
nohead.fields.create("posts", name="Summary", key="summary", type="long_text")

# Changes that rewrite records go through a migration; preview first
preview = nohead.migrations.create("posts", field_id="fld_...", type="long_text", dry_run=True)
migration = nohead.migrations.create("posts", field_id="fld_...", type="long_text")
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

Event types are the activity log's (`record.published`, `record.restored`, `field.updated`, `asset.purged`, ...), and a webhook subscribes to types or wildcards (`record.*`, `*`). `unwrap` checks the signature and the timestamp (Standard Webhooks), and raises `WebhookVerificationError` if either is off, or if the secret is unset (`None` or empty, as from a missing environment variable). A header repeated as a list of values, as some frameworks give it, counts as its values separated by spaces. After `rotate_secret`, requests carry a signature for the old secret and the new one for 24 hours, so switch the receiver's secret within that day (or end it sooner with `webhooks.secrets.retire`). Pass the raw body: parsing and re-serializing JSON changes the bytes.

`event.data` is the payload. For convenience, `event.record`, `event.asset`, `event.collection`, `event.schema_change`, `event.field`, `event.draft` and `event.webhook` give its parts, and are None when the event has no such part; so do the IDs `event.draft_id` and `event.record_id` (`draft.*`, also once the draft is gone) and `event.field_id` (`field.*`). A purged asset (`asset.purged`) is only its `id` and `object`, an `AssetEventDataAsset`. `event.actor` and `event.via` say who made the change, through which client (`via` is None when not known). Like responses, an event that doesn't match the models is still returned, unvalidated, with a `NoheadWarning`.

It's also available as `nohead.webhooks.unwrap(...)` on a client. Events can arrive more than once, so deduplicate by the `webhook-id` header.

## Types and models

- **Responses:** Pydantic models, in `nohead.models`. The main ones (`Record`, `Draft`, `Collection`, `Field`, `Asset`, `Webhook`) are also importable from `nohead`.
- **They're lenient on purpose, because the API adds fields and values without notice:**
  - Fields the SDK doesn't know yet are kept, in `model_extra`.
  - Enums are plain strings.
  - A response that doesn't match the models at all is still returned, unvalidated, with a `NoheadWarning`, rather than raised.
- **Timestamps** are `datetime`s.
- **Request bodies** are typed with the TypedDicts in `nohead.params`, and filters with those in `nohead.types`, so a type checker catches a misspelled field.

## Reference

| Resource | Methods |
|---|---|
| `records` | `list`, `get`, `create`, `update`, `delete`, `restore`, `publish`, `unpublish`, `publication`, `get_schedule`, `schedule`, `unschedule`, `scheduled_changes`, `drafts`, `count`, `bulk`, `diff`, `search` |
| `drafts` | `create`, `list`, `get`, `update`, `discard`, `merge`, `schedule`, `unschedule` |
| `records.revisions` | `list`, `get`, `revert` |
| `revisions` | `get` (by its own `rev_` ID) |
| `search` | across the project |
| `collections` | `list`, `get`, `create`, `update`, `delete`, `restore`, `schema` |
| `collections.schema_changes` | `list`, `get` |
| `collections.search_index` | `get`, `rebuild` |
| `fields` | `list`, `get`, `create`, `update`, `delete`, `restore`, `order`, `reorder`, `remove_alias` |
| `migrations` | `create`, `list`, `get`, `cancel` |
| `assets` | `upload`, `create_upload`, `complete`, `list`, `get`, `update`, `usage`, `delete`, `restore`, `purge` |
| `webhooks` | `list`, `get`, `create`, `update`, `delete`, `restore`, `rotate_secret`, `test`, `unwrap` |
| `webhooks.secrets` | `list`, `retire` |
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

Before pushing, run CI's checks, including that the generated files are current:

```bash
uv run ruff format --check . && uv run ruff check . && uv run pyright && uv run pytest
uv run python scripts/generate.py && uv run python scripts/unasync.py && uv run python scripts/samples.py
git diff --exit-code                     # fails if a generated file was stale
```

**How the code is organized:**

- `openapi.json` is the API's published contract. `scripts/generate.py` derives three files from it:
  - `src/nohead/models.py`
  - `src/nohead/params.py`
  - the operation table, `src/nohead/_generated/operations.py`
- **The async client is the source.** `src/nohead/_async` is written by hand, and `scripts/unasync.py` generates the sync client in `src/nohead/_sync` from it. Edit only the async code.
- The tests' mock transport (`tests/conftest.py`) checks every request against its operation in the contract, and every reply against what the operation documents for its status (`tests/spec.py`), so a fixture can't drift from the API. Build replies from the contract's examples (`example_of("Asset", status="ready")`); wrap one that breaks the contract on purpose, such as a gateway's error page, in `raw()`. A `NoheadWarning` fails a test that doesn't expect it.
- `tests/test_contract.py` calls every public method of both clients. It fails when an API-key operation in the contract has no method, when a query parameter is never sent (no method takes it, or no call passes it), or when a request doesn't match its operation (method, path, query parameters and JSON body, against their schemas). Each call gets an example of its operation's response, built from the contract's schema, and must return it, parsed without a `NoheadWarning`.

The smoke test (`smoke/smoke.py`) runs the core flow against a real API, with both clients, using the built package. Nohead's own CI runs it on every API contract change.

```bash
uv build
NOHEAD_API_URL=http://localhost:3000 NOHEAD_API_KEY=nohead_sk_... \
  uv run --isolated --no-project --with "dist/nohead-$(uv version --short)-py3-none-any.whl" python smoke/smoke.py
```

## Releasing

1. Bump the version in `pyproject.toml` and `src/nohead/_version.py`, then `uv lock` (CI installs with `--locked`, which fails on a stale lockfile).
2. Add a section for it to `CHANGELOG.md` (`## 1.2.3`), which becomes the release's notes.
3. Merge to `main`. Its ruleset requires the **CI passed** check, so the commit goes through a pull request or a branch whose CI passed, and force pushes are refused.
4. Run the **SDK release** workflow in the Nohead API repository. It runs this commit's smoke test against the API and pushes the tag `v1.2.3`. Nobody else can push `v*` tags: a tag ruleset lets only that workflow's deploy key through.
5. The tag starts `.github/workflows/release.yml`. Its publishing job runs in the `release` environment, which only `v*` tags can use, and the registry's trusted publisher accepts only that environment. It checks the version and its notes, tests and builds, and publishes to PyPI through trusted publishing (no token, with attestations). Then it creates the GitHub release with the built files.

## License

MIT
