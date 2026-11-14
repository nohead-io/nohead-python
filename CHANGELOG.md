# Changelog

Changes to the `nohead` package that you can notice. Versions follow
[Semantic Versioning](https://semver.org): additive API changes are minor
releases; a change that could break your code is a major one. Each release's
section is its GitHub release's notes.

## 0.21.0

- A response whose compressed body can't be decompressed raises
  `APIConnectionError` ("The response from … could not be read") and is
  retried like a dropped connection, as the TypeScript and Ruby SDKs retry
  it. Before, httpx's own `DecodingError` reached your code, and the request
  wasn't retried. For an upload's bytes, it is the `UploadError`'s cause.

## 0.20.0

- The docs of `PrincipalApiKey.collections` say what it counts since the API
  limits collections per project: the key's project's active collections, and
  how many the plan allows in one project. Nothing else changed: the SDKs
  share one version, and this release matches the TypeScript SDK's 0.20.0.

## 0.19.0

- **Breaking:** `image_url` refuses a processing option image URLs don't take,
  naming it, instead of building a URL that answers 404: imgproxy Pro's
  options, such as `sa`, `mc` or `co`, and presets other than `pr:preview`.
  The ones image URLs take are listed in the images guide.
- `fields.update` and `migrations.create` take `configuration` as a change the
  API merges onto the field's options (`FieldConfigurationChange`): an option
  sent replaces its value, `None` removes it, and the rest stay.
- Uploads send a content type only when one is given; without it, the API
  types the file by its filename, the same for every client and from a far
  wider list than the SDKs knew (a `.mov` is `video/quicktime` and gets a
  `media_url`). The SDKs' own extension table is gone.

## 0.18.0

No changes in this SDK: the SDKs keep one version, and this release moves the
TypeScript SDK's Astro loader and image service to a package of their own,
`@nohead/astro`.

## 0.17.0

No changes in this SDK: the SDKs keep one version, and this release adds the
TypeScript SDK's Astro loader option `references`, naming the Astro collection a
related collection is loaded as.

## 0.16.0

No changes in this SDK: the SDKs keep one version, and this release gives the
TypeScript SDK's Astro loader entries their record's `published_at`, `created_at`
and `updated_at`.

## 0.15.1

No changes in this SDK: the SDKs keep one version, and this release stops the
TypeScript SDK's Astro image service from making an image's fallback `src` at
the original's full size.

## 0.15.0

- The client reads `NOHEAD_API_URL` as its default `base_url`, as the CLI
  does, so one environment points both at the same API (before, a script
  sent its key to `https://api.nohead.io` whatever the CLI used). An explicit
  `base_url` still wins.
- `records.create` takes `publish=True`: the record is created published in
  one request (with `upsert_on`, a record already published stays so).
- `assets.upload` and `assets.create_upload` take `alt`, the asset's alt text
  from the start, so no `assets.update` follows each upload.
- `me.get()`'s `api_key` has `collections`: for a key with `schema:write`,
  its organization's active collections across all its projects and the
  plan's limit (`None` when unlimited), so a script can check new
  collections fit before creating any; `None` for other keys.

## 0.14.0

No changes in this SDK: the SDKs keep one version, and this release gives
the TypeScript SDK's Astro loader its schema and types, and its image
service defaults from astro.config.

## 0.13.0

No changes in this SDK: the SDKs keep one version, and this release adds
Astro support and image-loader fixes to the TypeScript SDK.

## 0.12.0

- `webhooks.create` and `webhooks.update` take `published_only`, and every
  webhook has it: a published-only webhook sends only the events that change
  what a published-only API key reads (a record published, unpublished or
  edited while live, schema changes, changes to assets that published records
  use), and skips drafts, schedules and edits to unpublished records.
- Audit events have `note`: the change note (`Nohead-Change-Note`) a record
  or schema change was made with, or `null`.

## 0.11.0

- `records.diff` takes `rich_text`, and the client's `rich_text` now applies to
  it: a rich text field's `before` and `after` read as HTML or Markdown
  instead of documents. A revert preview's `changes` follow `rich_text` too.

## 0.10.0

- `rich_text`, a client option (and a `with_options` one) and an option of the
  methods that return records or drafts, reads rich text fields as `"html"` or
  `"markdown"`: their values are strings instead of documents. A call's own
  `rich_text` overrides the client's. Writing Markdown already worked: `data`
  is sent as it is.

## 0.9.0

- **Breaking:** the client no longer reads `NOHEAD_API_URL`: a stray value
  sent requests, with the API key, to another host. The base URL is
  `base_url`, else `https://api.nohead.io`; pass `base_url` to use another
  API, as in `Nohead(base_url=os.environ["NOHEAD_API_URL"])`.

- `on_retry`, a client option (and a `with_options` one), is called before
  each retry's wait, also for an upload's bytes, with a `RetryEvent`: the
  attempt, the delay in seconds, the URL, and the status or error that failed.

- A path value of `.` or `..`, such as `records.get("..")`, raises
  `NoheadError` (`Invalid record_id: ".."`) before sending anything, instead
  of requesting the parent path (URL parsers resolve them, encoded or not).

- An empty `project_id` counts as not given (the project is looked up), as an
  empty `api_key` and `base_url` already did.

- A `base_url` that isn't an `http` or `https` URL raises `NoheadError`
  ("base_url must be an http or https URL") when the client is built,
  instead of failing each request.

- Headers are matched without regard to case and each is sent once: a client
  `headers` entry such as `authorization` replaces the SDK's `Authorization`
  instead of being sent as a second line, and the headers a call's options
  set (`Content-Type`, `Idempotency-Key`, `If-Match`, `Nohead-Change-Note`)
  always win. `with_options(headers=...)` replaces a header of the same name
  in any case.

- `if_match` takes a mapping with a `revision` (`{"revision": 3}`), and
  raises `TypeError` before sending for anything that isn't a revision
  number or doesn't have one.

- A naive `datetime` in a body or query raises `ValueError` ("... has no time
  zone: pass an aware datetime") instead of being sent without one, when its
  moment depends on where the code runs.

- `nan` and infinities in a body raise `ValueError` instead of being sent as
  `NaN` and `Infinity`, which aren't JSON.

- Calls that need the project at the same time share one `GET /v1/me`
  lookup, also with clients from `with_options`, instead of each making one.

- A redirect from the API raises `APIError` (`301 redirect: The API answered
  with a redirect to <URL>; check the base URL`), and neither API requests nor
  an upload's bytes follow redirects, even with an `http_client` that does.

- A list response that isn't a list (not a JSON object with `data` and
  `meta`) raises `NoheadError` ("The API's response could not be read (HTTP
  200)") instead of `TypeError` or `KeyError`.

- `Retry-After` is read as the other Nohead SDKs read it: a number of seconds
  (`5`, `1.5`) or an HTTP date in any of its three forms, always GMT.
  Anything else (`-1`, `+5`, `.5`, `1e3`, `inf`, `nan`, an ISO 8601 date) is
  ignored and the usual backoff applies; `inf` made the request raise at
  once, and `nan` retried without waiting. An asctime date was read in the
  computer's time zone.

- `assets.upload` raises `UploadError` (`Could not upload <filename>:
  <reason>`, with the connection error as its cause) when storage can't be
  reached or times out, instead of `APIConnectionError` or `APITimeoutError`.

- `unwrap` with a `None` secret raises `WebhookVerificationError` ("The
  webhook secret is empty") instead of `AttributeError`, and takes a header
  given as a list of values (as some frameworks give a repeated header),
  joined with spaces, instead of raising `TypeError`.

- `image_url` takes an asset as a mapping (`{"image_url": ...}`), and
  `fit=None` means the default, `contain`.

- A field (`Field`, `FieldCreate`) is validated as the model its `type`
  names, and a batch result as the one its `status` names, instead of
  against every variant: a response that doesn't match the models warns with
  that model's name and its own differences (3, say, instead of 43), and an
  unknown `type` is a single difference. `Field` and `FieldCreate` are now
  `Annotated` unions, so `isinstance(value, Field)` raises `TypeError`; check
  the model (`isinstance(field, TextField)`) or `field.type` instead.

- A `NoheadWarning` (a deprecated operation, usage over a plan limit, or a
  response that doesn't match the models) points at the line of your code
  that made the call, iterated the pages or read the webhook event, instead of
  a line inside the SDK, so `warnings` filters by module and the default
  once-per-location display work.

- `unwrap` refuses an empty secret (`""` or `"whsec_"`, as from an unset
  environment variable) with `WebhookVerificationError` ("The webhook secret
  is empty"), instead of reporting that no signature matches.

- `unwrap` raises `WebhookVerificationError` for every malformed request:
  a webhook header with a non-ASCII character raised `TypeError` or
  `UnicodeEncodeError`, and a secret with one `ValueError`.

- The package declares its `typing-extensions` dependency (4.12 or later).

- `assets.upload` of a pipe or socket without `byte_size` raises
  `UploadError` ("needs byte_size"), as for any stream that cannot seek,
  instead of declaring the size of what the pipe had buffered (nothing, on
  Linux).

- A missing or empty path value, such as `records.get("")`, raises
  `NoheadError` ("Missing record_id") before sending anything, instead of
  requesting another URL (`GET /v1/records/`, a `NotFoundError`).

- `assets.upload` guesses the content type from the filename's extension with
  the same table as the other Nohead SDKs (images, PDF, JSON, text, Markdown,
  CSV, MP3, MP4, WebM and ZIP), else `application/octet-stream`, so it no
  longer depends on the platform and Python version (`mimetypes`). Pass
  `content_type` for any other type.

- A request that cannot be sent at all (a `base_url` with an unsupported
  scheme, a header httpx refuses) raises `NoheadError` straight away
  ("Could not send the request"), instead of being retried and reported as
  `APIConnectionError` ("Could not reach"). A dropped connection, a timeout
  and a network or proxy error are still retried.

- `image_url` writes numbers as the other Nohead SDKs do: a whole float
  without `.0` (`width=800.0` is `800`, `quality=80.0` is `q:80`) and `dpr`
  in full (`1.2345678`, which was cut to 6 significant digits). `width`,
  `height` and `quality` are typed as `float`, so computed sizes type-check.

## 0.8.0

- `Asset` has `file_url`, the file as uploaded, which downloads under its
  filename, and for video and audio `media_url`, which plays it inline (in
  `<video>` and `<audio>`, with range requests). Both are open, never expire
  and are cached on a CDN, like `image_url`.

- `assets.download_url` is removed, with the API's
  `GET /v1/assets/{asset_id}/download-url` and its 2-minute links: use the
  asset's `file_url`.

- An upload larger than the plan allows (10 MB a file on Free, 100 MB on paid
  plans) is refused with a `PlanLimitExceededError` when it starts.

## 0.7.0

- `assets.list(q=..., kind=...)`: `q` finds assets whose filename or alt
  text has every word, ignoring case; `kind` lists only `image`, `video`,
  `audio`, `document` or `other` assets, or several kinds as a list.

## 0.6.0

- API keys now start `nohead_sk_`, or `nohead_pk_` for published-only keys;
  keys in the old `sk_live_` format no longer work. The SDK sends whatever key
  it's given, so only the docs and examples change.

- `assets.update(asset, filename=..., alt=...)` renames an asset and sets
  its alt text (`PATCH /v1/assets/{asset_id}`). `Asset` has `alt` (a string
  or `None`), and webhooks can subscribe to `asset.updated`.

- Image URLs are open. `Asset` has `image_url`, the whole image, and the new
  `nohead.images.image_url` writes any of imgproxy's processing options into
  it, without a request.

- **Breaking:** `assets.image_url` is gone, with the API's
  `GET /v1/assets/{asset_id}/image-url`: use `nohead.images.image_url`, which
  needs no request.

- **Breaking:** `Collection` has no `search_enabled`, and `SearchIndex` no
  `enabled`, and collections' `create` and `update` no longer take
  `search_enabled`: API keys search every collection they can read.

- `revisions.get(revision)` reads a revision by its own `rev_` ID, as
  webhooks and the activity log name it (`GET /v1/revisions/{revision_id}`).

- `records.create` takes `upsert_on`, a unique field's key: the record
  holding that value is updated instead, if one exists, and `if_match`
  applies to that update.

- Collections have `public_search`: whether the project's search tokens find
  their published records. Off by default;
  `collections.create(public_search=...)` and `collections.update` take it. A
  collection's search index has `index`, the name a token searches it by.

## 0.5.0

- **Breaking:** a field migration is created under its collection:
  `migrations.create(collection, field_id=..., ..., dry_run=...)`
  (`POST /v1/collections/{collection_id}/migrations`) replaces
  `fields.migrate(field, ...)`, which is gone. It returns the same: a
  `FieldMigrationPreview` for a dry run, a `FieldMigration` otherwise.
- **Breaking:** `drafts.list` no longer takes `record_id`; a record's draft
  is `records.drafts(record)`.
- **Breaking:** `assets.list(content_type=...)` takes one MIME type or
  `type/*` wildcard as a string (`"image/*"`), or several as a list
  (`["image/*", "application/pdf"]`, up to 50). A comma-separated string is
  no longer split into several.
- **Breaking:** `audit_events.list` sorts by `created_at` or `-created_at`
  (was `id` or `-id`), and `records.list` no longer sorts by `id`.
- **Breaking:** a webhook event's `actor` and `via` are always there:
  `event.actor` is an `Actor`, no longer None, and `event.via` is None only
  when the client is not known. An event without them is returned
  unvalidated, with a `NoheadWarning`. `via` is no longer `import` or
  `migration`.

## 0.4.0

- **Breaking:** a field's `api_key` is its `key` (in fields, their aliases,
  `fields.create(key=...)` and `fields.update(key=...)`), as the editor's
  "Field key" says. API keys keep their name.
- **Breaking:** `collections.schema_changes.get(schema_change)` takes the
  schema change's ID alone (`GET /v1/schema-changes/{id}`).
- **Breaking:** `fields.update` no longer takes `type` or `multiple`; they
  rewrite record values, so they are `fields.migrate`. The API refuses a
  body key an operation doesn't take with `400` (`unknown_parameter`, naming
  it), so a misspelt keyword no longer passes unnoticed.
- Fields are typed per field type: a field is a `TextField`, `EnumField`,
  `RelationField`... (`Field` is their union), with its `configuration` as
  `TextFieldConfiguration`, `EnumFieldConfiguration`... `fields.create`'s
  `configuration` takes any of them.

## 0.3.0

- **Breaking:** 0.1 and 0.2 no longer work with the current API: its paths
  changed, so upgrading is required.
- `change_note` is sent percent-encoded (UTF-8), so change notes work in any
  language: a note outside ASCII used to fail the request.
- Drafts: changes to a record that wait until they are merged into it, now
  or at a set time. `drafts.create`, `list`, `get` (with `expand`, for
  previews), `update`, `discard`, `merge`, `schedule` and `unschedule`, and
  `records.drafts`. `records.publish` on a live record with a pending draft
  is a `ConflictError` (`draft_pending`). Webhook events have `event.draft`,
  `event.draft_id` (`draft.*`, and a merge's `record.updated`) and
  `event.record_id` (`draft.*`). `Draft` is importable from `nohead`.
- **Breaking:** the models for what only the web app can do (organizations,
  projects, members and invitations, billing, API keys, usage, account
  changes and redaction, such as `Organization`, `Project`, `ApiKeyWithToken`,
  `Billing`) are gone. Those operations need a signed-in person, so an API
  key could never call them, and the API reference no longer lists them.
- **Breaking:** the API is resource-oriented. Method names stay; what they
  return and take follows it:
  - Records have no `status`, `schedule` or `deleted`: a record is published
    when `published_at` is set, and has `deleted_at` and `purge_after`.
    Filter with `{"published_at": {"exists": True}}`. `records.get` returns
    deleted records too (no `include_deleted`).
  - `records.schedule` sets the whole schedule: a time left out is cleared,
    and `clear=` is gone. It and `unschedule` return the schedule, and
    `records.get_schedule`, `records.publication` and
    `records.scheduled_changes` are new.
  - `records.bulk` returns a `RecordBatch`, whose `results` are each a
    `RecordBatchResultsSucceeded` (with the `record`) or a
    `RecordBatchResultsFailed` (with the `error`), by `status`.
  - `search` takes `filter={"published_at": {"exists": True}}` instead of
    `status="published"`, as record lists do.
  - `records.diff` takes `from_revision=` and `to_revision=` as keywords, and
    `fields.reorder` takes `field_ids=`.
  - `audit_events.list` filters by `type` (was `action`), `resource_type` (one,
    or a list of several), `resource_id`, `actor_type`, `actor_id` and a
    `created_at` range (`{"gte": ..., "lt": ...}`, was `since` and `until`),
    and events have `type` instead of `action`. `records.revisions.list`
    filters by a `created_at` range too, and revisions' `operation` can be
    `merge`. The filters are typed (`AuditEventFilter`, `RevisionFilter` in
    `nohead.types`); an unknown filter is an `InvalidRequestError`.
  - Collections, fields, assets and webhooks have `deleted_at` and
    `purge_after` instead of `deleted`, and migrations
    `cancel_requested_at`. `ScheduledChange` has no `last_error`, and
    `SchemaChange` no `status`.
  - `assets.create_upload` returns the asset with its `upload`.
  - `fields.reorder` returns the `FieldOrder`; `fields.order` reads it, and
    `fields.get` reads one field, deleted ones too.
  - `records.restore` takes `if_match`, and `records.revisions.revert`
    `change_note`.
  - Webhook event types are the activity log's (`record.restored`,
    `field.updated`, ..., and wildcards such as `record.*`; no
    `record.imported`), and events carry `actor` and `via`;
    `event.collection` (now with `object`) and `event.schema_change` are
    dicts, and `event.field` and `event.field_id` (`field.*`) are new. A
    purged asset's `event.asset` is only its `id` and `object`, an
    `AssetEventDataAsset`. `webhooks.rotate_secret` returns a
    `WebhookSecretWithValue`; the old secret signs for 24 hours more.
    `webhooks.secrets.list`, `webhooks.secrets.retire`, `webhooks.restore`
    and `webhooks.list(deleted=True)` are new.
  - Models renamed with the API's schemas: `AssetUpload` is
    `AssetWithUpload` (its `upload` an `AssetUploadTarget`),
    `BulkRecordsRequest` and `BulkRecordsResult` are `RecordBatchRequest` and
    `RecordBatch`, and `ChangeVia` is `Via`.
- **Breaking:** the `datetime` field type is now `date`. A plain date field holds
  `YYYY-MM-DD`; with `include_time` it holds a moment, written in the field's
  `time_zone` when it has one. Field migrations take `time_zone`, the zone
  whose day each moment falls on when the time is removed.
- Boolean fields can't be `required`: a boolean is true or false, and no
  value reads as false.
- Text fields take a `format` (`email`, `url`, `slug`; slugs are always
  unique) and text and integer fields `unique`; a taken value's error detail
  has the `record_id` that has it (`code: "taken"`).
- Filters take operators: `{"price": {"lt": 50}}`, with `eq`, `ne`, `gt`,
  `gte`, `lt`, `lte`, `in` (a list) and `exists`, and record lists sort by a
  field's value (`RecordSort` is now any string). Commas and backslashes in
  list values are escaped, so a value can hold a comma.
- Date filters take `today`, and dates with a time `now`.
- `assets.usage()`: where an asset is used, as counts of the records that use
  it (and of those, the published ones) and the 10 most recently updated with
  the fields that use it. Needs the `records:read` scope too.
- `assets.purge()`: permanently deletes a deleted asset now, instead of at
  its `purge_after`, and frees its storage.
- `assets.upload()` with an `idempotency_key` resumes: run again, it returns
  an asset that is already `ready` without sending the bytes again, and
  raises `UploadError` once the upload's URL has expired (start over with a
  new key).
- Webhook events are lenient, as responses are: an event, or a part of one
  (`event.record`, `event.asset`, ...), that doesn't match the models is
  returned unvalidated with a `NoheadWarning`, instead of raising
  (`WebhookVerificationError` or a Pydantic error).
- An unvalidated response is built as the variant of a union it says it is
  (a failed batch result stays a `RecordBatchResultsFailed`), and a list in
  an optional field no longer raises a `ValueError` while it is built.
- An error reads only the fields of the API's error envelope that have the
  right type, so JSON from a proxy or gateway that merely looks like one no
  longer gives it a non-string `message`, `type` or `request_id`, nor raises
  a `TypeError` while the error is built. An error detail that doesn't match
  the model keeps its fields, so a `code` such as `in_progress` still counts.

## 0.2.0

- Types follow the API's current contract. They add types only for
  operations an API key can't call, so no method changed.

## 0.1.0

The first release.

- `Nohead` and `AsyncNohead`, with the same methods for every operation an
  API key can call: records (with revisions, scheduling, bulk changes and
  search), collections, fields and migrations, assets, webhooks and their
  deliveries, the audit log, feature flags.
- Pages you can loop over (`for`, or `async for`), lenient Pydantic models,
  typed request bodies.
- Typed errors per API error type, retries with idempotency keys,
  `if_match` and change notes.
- `assets.upload()` in one call (paths, bytes or files), and webhook
  verification (`nohead.webhooks.unwrap`).
