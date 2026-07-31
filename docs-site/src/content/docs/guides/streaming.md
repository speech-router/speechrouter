---
title: Streaming transcription
description: The /v1/listen WebSocket — request shape, audio, and the event stream.
---

Open a WebSocket to `wss://api.speechrouter.ai/v1/listen`, send PCM audio
frames, receive normalized transcript events. Same contract for all 12
providers.

## Query parameters

| Param | Default | Meaning |
| --- | --- | --- |
| `model` | *(required)* | Model slug, e.g. `deepgram/nova-3` |
| `fallbacks` | — | Comma-separated failover lane, e.g. `soniox/stt-rt-v5,openai/gpt-4o-transcribe` |
| `encoding` | `linear16` | PCM encoding of the audio you send |
| `sample_rate` | `16000` | Sample rate in Hz |
| `channels` | `1` | Channel count |
| `language` | auto | BCP-47 hint where the model supports it |
| `interim_results` | `true` | Emit non-final hypotheses |
| `diarization` | `false` | Speaker labels (see per-model support) |
| `keyterms` | — | Comma-separated bias terms |
| `provider_params` | — | URL-encoded JSON object, [passed through raw](/providers/) |
| `include_raw` | `false` | Attach untouched provider payload to each transcript |

Auth goes in the `Authorization` header or the `['bearer', key]`
subprotocol — see [Authentication](/authentication/).

## Sending audio

- **Binary frames** are audio, in the encoding/rate you declared. Chunks of
  20–250 ms work well everywhere (providers with stricter pacing rules are
  re-paced by the gateway).
- **Text frames** are JSON control messages:

```json
{ "type": "finalize" }    // flush: force finals for audio sent so far, then done
{ "type": "keepalive" }   // keep an idle connection open
```

## The event stream

```json
{ "type": "session.open", "session_id": "…", "model": "deepgram/nova-3" }
{ "type": "speech_started", "at": 0.48 }
{ "type": "transcript", "is_final": false, "text": "speech router is", "start": 0.5 }
{ "type": "transcript", "is_final": true,  "text": "SpeechRouter is live.",
  "words": [{ "w": "SpeechRouter", "start": 0.5, "end": 0.9, "speaker": 0 }],
  "start": 0.5, "end": 1.9 }
{ "type": "utterance_end", "at": 1.9 }
{ "type": "done", "usage": { "audio_seconds": 12.4 } }
```

Full schemas: [WebSocket events](/reference/events/).

- `transcript.words[]` carries per-word timing (audio-time seconds from session
  start), confidence where available, and integer `speaker` labels when
  diarization is on.
- `utterance_end` is the endpointing signal — the "respond now" trigger for
  voice agents.
- If a provider dies mid-session you'll see
  `{ "type": "provider_switched", … }` and the stream continues on the next
  model in your lane — [failover](/guides/failover/) explains the guarantees.

## Ending a session

Send `{ "type": "finalize" }` and keep reading until `done`, or just close the
socket. Sessions with no audio for 60 seconds are closed as `audio_timeout`
(send `keepalive` to hold an idle line open).
