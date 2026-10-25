# Changelog

Changes to the `nohead` package that you can notice. Versions follow
[Semantic Versioning](https://semver.org): additive API changes are minor
releases; a change that could break your code is a major one. Each release's
section is its GitHub release's notes.

## Unreleased

- `unwrap` raises `WebhookVerificationError` for every malformed request:
  a webhook header with a non-ASCII character raised `TypeError` or
  `UnicodeEncodeError`, and a secret with one `ValueError`.

- The package declares its `typing-extensions` dependency (4.12 or later).

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
