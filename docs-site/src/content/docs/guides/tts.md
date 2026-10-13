---
title: Text-to-speech
description: POST /v1/audio/speech and the /v1/speak WebSocket — formats, voices, streaming, barge-in.
---

Two ways to synthesize speech, same models and voices:

| | `POST /v1/audio/speech` | `WSS /v1/speak` |
| --- | --- | --- |
| Input | Whole text per request | Text streamed in as `text.delta` fragments |
| Output | Audio file / chunked stream | Binary audio frames + `audio.chunk` metadata |
| Use for | Prompts, notifications, files | Voice agents speaking LLM output as it streams |
| Compatible with | OpenAI SDK (`audio.speech`) | SpeechRouter protocol |

40 models from 14 providers: OpenAI, Gemini, ElevenLabs, Cartesia, Deepgram Aura,
Azure, Google Cloud, Rime, Inworld, Fish Audio, MiniMax, Groq (Orpheus), Murf and
Speechmatics. The live list, voices, formats and prices per model:
[`GET /v1/models`](/reference/rest/#get-v1models) (entries with `"kind": "tts"`), or the
[provider pages](/providers/).

Voices are each provider's own ids: ElevenLabs voice ids, Azure voice names
(`en-US-JennyNeural`), Deepgram Aura model ids (`aura-2-thalia-en`) and so on. Models
marked `custom_voices` accept any id your provider account can use, such as cloned or
library voices.

## POST /v1/audio/speech

OpenAI's request shape with a SpeechRouter slug in `model`, so the OpenAI SDK
works by changing `base_url`:

```python
from openai import OpenAI

client = OpenAI(api_key="sk_sr_...", base_url="https://api.speechrouter.ai/v1")
with client.audio.speech.with_streaming_response.create(
    model="openai/gpt-4o-mini-tts",
    voice="coral",
    input="Your appointment is confirmed for Tuesday at ten.",
    response_format="mp3",
) as response:
    response.stream_to_file("confirmation.mp3")
```

```bash
curl https://api.speechrouter.ai/v1/audio/speech \
  -H "Authorization: Bearer $SPEECHROUTER_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model": "gemini/gemini-3.8-flash-tts", "voice": "Puck",
       "input": "Hello there", "response_format": "wav"}' --output hello.wav
```

| Field | Default | Meaning |
| --- | --- | --- |
| `model` | *(required)* | TTS slug |
| `input` | *(required)* | Text, up to the model's `max_input_chars` (4096) |
| `voice` | model default | Provider-native voice id (`capabilities.voices`) |
| `response_format` | `mp3`, or `wav` for pcm-only models | `mp3` `opus` `aac` `flac` `wav` `pcm` `mulaw` `alaw` — per model |
| `sample_rate` | native (24000); 8000 for `mulaw`/`alaw` | `pcm`/`wav`/`mulaw`/`alaw` only: `24000` or `8000` |
| `speed` | — | 0.25–4.0, models with `capabilities.speed` (`tts-1*`) |
| `instructions` | — | Style prompt ("warm, unhurried"), models with `capabilities.instructions` |
| `language` | — | BCP-47 hint (Gemini) |
| `stream` | `true` | `false` buffers the whole file and adds `X-SpeechRouter-Cost-Usd` |
| `provider_params` | — | Passed to the vendor; cannot override the fields above |

Audio streams back with chunked transfer as the provider generates it.
Headers: `X-SpeechRouter-Request-Id`, `X-SpeechRouter-Model`,
`X-SpeechRouter-Characters`. Errors before the first byte use the
[standard envelope](/reference/errors/). After the first byte the status is
already sent, so a provider failure ends the stream early.

### Formats

Gemini produces raw 24 kHz PCM only; SpeechRouter wraps it as `wav`, and
encodes `mulaw`/`alaw` (G.711) at 8 kHz for telephony. OpenAI models produce
every format natively, plus the same 8 kHz G.711 output. `pcm` is signed
16-bit little-endian mono (`audio/L16;rate=24000;channels=1`).

## WSS /v1/speak

For voice agents: stream text in as your LLM produces it, get audio back
sentence by sentence.

```
wss://api.speechrouter.ai/v1/speak?model=openai/gpt-4o-mini-tts&voice=marin&encoding=linear16
```

Query: `model`, `voice`, `encoding` (`linear16` | `mulaw` | `alaw` | `mp3` |
`opus`, per model), `sample_rate`, `speed`, `language`, `instructions`,
`provider_params`. Auth as for [`/v1/listen`](/authentication/).

| Client → server | Meaning |
| --- | --- |
| `{"type": "text.delta", "text": "…"}` | Append text |
| `{"type": "finalize"}` | No more text: speak what's left, then `done` |
| `{"type": "clear"}` | Barge-in: drop everything queued and in flight |
| `{"type": "keepalive"}` | Hold an idle session open |

| Server → client | Meaning |
| --- | --- |
| `session.open` | Resolved model, voice, encoding, sample rate |
| `audio.chunk {seq, start}` | Immediately followed by exactly one binary audio frame |
| `cleared {last_seq}` | Ack for `clear`: chunks with `seq <= last_seq` were the last pre-clear audio |
| `done {usage}` | Totals: characters, audio seconds, units, cost |
| `error` | Terminal error |

How it works: OpenAI and Gemini take whole text per request, so the gateway
segments your stream at sentence boundaries (and at word boundaries if the
text pauses for ~400 ms mid-sentence), synthesizes one segment ahead of the
one playing, and always delivers in order. `audio.chunk.start` is the audio
time in seconds of that chunk within the session.

```python
import asyncio, json, websockets

async def speak(tokens):
    url = "wss://api.speechrouter.ai/v1/speak?model=openai/gpt-4o-mini-tts&encoding=linear16"
    async with websockets.connect(url, subprotocols=["bearer", "sk_sr_..."]) as ws:
        print(json.loads(await ws.recv()))           # session.open
        for token in tokens:
            await ws.send(json.dumps({"type": "text.delta", "text": token}))
        await ws.send(json.dumps({"type": "finalize"}))
        async for frame in ws:
            if isinstance(frame, bytes):
                play(frame)                          # 24 kHz s16le mono
            elif json.loads(frame)["type"] == "done":
                break
```

### Provider notes

- **Google Cloud** synthesizes the whole clip before responding (its REST API doesn't
  stream), so time to first byte equals total synthesis time.
- **Groq Orpheus** takes at most 200 characters per request. `/v1/speak` segments for
  you; `/v1/audio/speech` rejects longer input.
- **Speechmatics** renders 16 kHz natively (8 kHz G.711 is derived).
- **Fish Audio** bills per UTF-8 byte, so CJK text costs about 3x per character.

## Billing

TTS bills in the vendor's unit: **per character** (`tts-1`, `tts-1-hd`) or
**per token** (`gpt-4o-mini-tts`, Gemini: text-in + audio-out tokens, as the
provider reports them). Audio a barge-in cancelled was still generated and
billed upstream, so it is billed. See [Pricing](/guides/pricing/).

TTS is behind a feature flag (`SPEECHROUTER_ENABLE_TTS`), on by default for
self-hosting.
