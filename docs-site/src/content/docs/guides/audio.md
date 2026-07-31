---
title: Audio formats
description: Encodings, sample rates, channels, and how to chunk streaming audio.
---

## Streaming input

Declare what you'll send in the connection params; the gateway rejects
model/encoding combinations that can't work **at connect time**, not
mid-stream:

| Param | Default | Notes |
| --- | --- | --- |
| `encoding` | `linear16` | Raw 16-bit little-endian PCM — supported everywhere |
| `sample_rate` | `16000` | 16 kHz is the sweet spot for every provider |
| `channels` | `1` | Mono unless the model supports more |

`linear16` @ 16 kHz mono is the universal safe choice and what the SDK
examples assume. Telephony audio (`mulaw` @ 8 kHz) and compressed input
(`opus`, `ogg-opus`) are supported where the provider supports them — each
[provider page](/providers/) lists its encodings.

### Chunking

Send binary frames of **20–250 ms** of audio. Two provider quirks the gateway
absorbs so you don't have to:

- **Minimum chunk sizes** (e.g. AssemblyAI rejects < 50 ms): sub-minimum
  chunks are coalesced before forwarding.
- **Real-time pacing** (some providers close the socket if audio arrives
  faster than real time): the gateway re-paces bursts.

So: send audio as it arrives from your source, at whatever cadence — the
gateway does the per-vendor conditioning.

### Sample-rate conversion

Providers with fixed input rates (e.g. OpenAI realtime wants 24 kHz) get
gateway-side resampling from your declared rate. Declare what you actually
have; never resample client-side.

## Batch input

`POST /v1/audio/transcriptions` accepts whatever container the model accepts —
WAV, MP3, FLAC, OGG, M4A and friends — up to 250 MB. The gateway forwards your
file's content type; no transcoding is applied.
