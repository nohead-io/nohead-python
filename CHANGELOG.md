# Changelog

Changes to the `nohead` package that you can notice. Versions follow
[Semantic Versioning](https://semver.org): additive API changes are minor
releases; a change that could break your code is a major one. Each release's
section is its GitHub release's notes.

## 0.3.0

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
- `assets.purge()`: permanently deletes a deleted asset now, instead of 30
  days after the delete, and frees its storage.

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
