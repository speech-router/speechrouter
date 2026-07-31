---
title: Authentication
description: API keys, WebSocket auth, and short-lived client tokens for browsers.
---

## API keys

Keys are minted in the [console](https://speechrouter.ai) and start with
`sk_sr_`. REST endpoints take a standard Bearer header:

```bash
curl -H "Authorization: Bearer sk_sr_..." https://api.speechrouter.ai/v1/models
```

## WebSocket auth

Browsers can't set headers on WebSockets, so `/v1/listen` accepts credentials
three ways, in order of preference:

1. **`Authorization: Bearer <key>` header** — for server-side connections.
2. **`Sec-WebSocket-Protocol: bearer, <key>`** — the subprotocol pair, for
   browsers. Keys stay out of URLs and access logs:
   ```js
   new WebSocket('wss://api.speechrouter.ai/v1/listen?model=deepgram/nova-3',
                 ['bearer', token])
   ```
3. **`?api_key=` query param** — works, but URLs get logged; prefer 1 or 2.

## Short-lived client tokens

For browser and mobile apps, never embed `sk_sr_` keys. Mint a disposable token
server-side and hand that to the client:

```bash
curl -s -X POST https://api.speechrouter.ai/v1/tokens \
  -H "Authorization: Bearer $SPEECHROUTER_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"ttl_seconds": 60}'
```

```json
{ "token": "st_…", "expires_at": "2026-07-31T20:14:09Z", "ttl_seconds": 60 }
```

- TTL is **10–300 seconds** (default 60) — long enough to open a WebSocket,
  short enough to be worthless if leaked.
- Tokens inherit the parent key's org, billing, and limits.
- A session opened with a token **keeps running after the token expires** — the
  token gates the handshake, not the stream.
- Tokens cannot mint tokens.

The SDKs wrap this as `sr.createToken({ ttlSeconds })` / `sr.create_token(ttl_seconds=60)`.
