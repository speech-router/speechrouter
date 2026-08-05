# Telnyx -- protocol brief (verified 2026-08-04)

## Streaming WS `wss://api.telnyx.com/v2/speech-to-text/transcription`

- Auth: `Authorization: Bearer <key>` header on the WS upgrade.
- All config is URL query params. **Do NOT send a JSON config frame after
  connect** -- it is ignored and produces no response. This was verified by
  wasting iterations on a config-frame approach that connected cleanly but
  returned zero transcripts; switching to URL query params produced
  transcripts immediately.
- `transcription_engine` selects the upstream model: `Telnyx` (in-house),
  `Deepgram`, `Google`, `Azure`. Only `Telnyx` is exposed in this adapter;
  the other three have their own first-class adapters in this repo.
- `input_format`: `linear16`, `mulaw`, `alaw`.
- `sample_rate`: e.g. 8000, 16000.
- `language`: optional BCP-47 (e.g. `en-US`). The engine auto-detects if
  omitted.

### URL construction

```
wss://api.telnyx.com/v2/speech-to-text/transcription
  ?transcription_engine=Telnyx
  &input_format=linear16
  &sample_rate=16000
```

### Up wire

Raw PCM audio as **binary WebSocket frames** (16-bit little-endian, mono).
No base64, no JSON wrapping. Send at any chunk size; no provider-side
pacing enforcement observed.

### Down wire

One JSON text frame per finalized transcript:

```json
{"transcript":" Hello world, this is a test of speech to text.",
 "confidence":null,"is_final":true}
```

- **No interim frames.** The Telnyx engine emits exactly one final
  transcript after audio stops arriving, then closes the socket (1000 OK).
  Adding `interim_results=true` to the URL **suppresses ALL output** from
  the Telnyx engine (verified) -- `Capabilities.interim_results` is False.
- **No word timestamps**, no speaker labels, no `speech_started`, no
  `utterance_end`, no `speech_final`. Confidence is `null` on the Telnyx
  engine (non-null on the Deepgram engine proxied via the same endpoint).
- **No endpointing signal.** The session layer's silence timeout is the
  only utterance boundary; `Capabilities.endpointing` is False.
- Empty `transcript` strings are silence -- skip them.

### Shutdown

No `CloseStream` frame -- that is documented for Deepgram/Speechmatics/
Soniox engines only. The server flushes and closes on its own once audio
stops arriving. `finish()` is a no-op marker; `close()` closes the socket.

### Error frames

`{"errors": [...]}` -- not transcript data; skip.

### Billing

Per minute of audio processed. $0.025/min for the Telnyx in-house engine
(verified 2026-08-04 via telnyx.com/pricing/speech-to-text and the release
notes at telnyx.com/release-notes/new-speech-to-text-engine).
