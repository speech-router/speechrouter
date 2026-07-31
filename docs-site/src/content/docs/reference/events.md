---
title: WebSocket events
description: Every frame on the /v1/listen socket, both directions.
---

All events are JSON text frames with a `type` discriminator. Audio itself is
binary frames. Unknown fields may be added over time — parse leniently.

## Server → client

### `session.open`

First frame after the handshake.

```json
{ "type": "session.open", "session_id": "sess_…",
  "model": "deepgram/nova-3", "encoding": "linear16", "sample_rate": 16000 }
```

### `transcript`

The core event. `is_final: false` frames are hypotheses superseded by the next
final covering that audio.

```json
{ "type": "transcript", "is_final": true,
  "text": "Never lose a word.",
  "words": [
    { "w": "Never", "start": 2.5, "end": 2.71, "conf": 0.98, "speaker": 0 }
  ],
  "start": 2.5, "end": 3.45, "lang": "en" }
```

- `words[].start` / `end` — audio-time seconds from the first sample of the
  session, **monotonic across failover**.
- `speaker` — integer labels when diarization is on.
- `provider_raw` — the untouched vendor payload, only with `include_raw=true`.

### `speech_started`

Voice activity began: `{ "type": "speech_started", "at": 0.48 }`.

### `utterance_end`

Endpointing — the "respond now" signal for voice agents:
`{ "type": "utterance_end", "at": 3.45 }`.

### `provider_switched`

Mid-stream failover marker — fields and dedup guarantees in
[Failover](/guides/failover/).

### `done`

Last frame before close:

```json
{ "type": "done", "usage": { "audio_seconds": 12.4, "model": "deepgram/nova-3" } }
```

### `error`

```json
{ "type": "error", "code": "provider_error", "message": "…",
  "provider": "deepgram", "recoverable": true }
```

`recoverable: true` means the stream continues (e.g. failover is in
progress). Terminal errors close the socket. Codes:
[Errors & close codes](/reference/errors/).

## Client → server

| Frame | Meaning |
| --- | --- |
| *(binary)* | Audio in the declared encoding/sample rate |
| `{ "type": "finalize" }` | Flush: force finals for all audio sent, emit `done`, close |
| `{ "type": "keepalive" }` | Hold an idle session open (send every ~8s of silence) |

Sessions idle for 60 seconds — no audio and no keepalive — close with
`audio_timeout`.
