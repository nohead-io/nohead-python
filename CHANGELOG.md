# Changelog

Changes to the `nohead` package that you can notice. Versions follow
[Semantic Versioning](https://semver.org): additive API changes are minor
releases; a change that could break your code is a major one. Each release's
section is its GitHub release's notes.

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
