# Contributing

## Dev setup

```sh
cd gateway
uv sync                      # Python 3.14; extras: uv sync --extra azure --extra google
uv run pytest -q             # fixture tests, no network
uv run ruff check . && uv run pyright
```

SDKs:

```sh
cd packages/sdk-ts && npm install && npm test
cd packages/sdk-python && uv sync && uv run pytest -q
```

## Adding a provider

1. Start from the protocol notes in `docs/providers/` — write yours from the
   vendor's primary docs, not memory. This file is the review artifact.
2. Implement `STTStreamProvider` and/or `STTBatchProvider`
   (`gateway/speechrouter_gateway/providers/base.py`) in a new
   `providers/<name>/` package. Adapters stay thin: the session engine owns
   failover, timestamp offsets, and billing. Timestamps you emit are
   adapter-relative; `connect()` returns only when the provider is ready for
   audio.
3. Add `models.json` (slugs, modes, capabilities, pricing) and register in the
   provider registry.
4. Add fixture tests mirroring real captured payloads — they verify our
   reading of the protocol; a live smoke against the vendor verifies reality.

## Ground rules

- The spec (`packages/spec`) is the source of truth. Wire changes start there;
  gateway models are code-generated from it and CI fails on drift.
- Every event field a provider gives us is either normalized or available via
  `include_raw` — never silently dropped.
- Sign off your commits (`git commit -s`) — we use the
  [Developer Certificate of Origin](https://developercertificate.org).
