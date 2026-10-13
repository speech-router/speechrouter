---
title: Live voice (realtime)
description: OpenAI Realtime and Gemini Live through SpeechRouter with the vendors' own SDKs.
---

SpeechRouter proxies **OpenAI Realtime** and **Gemini Live** speech-to-speech
sessions. You keep using the vendor's own SDK and protocol (tools, function
calls, VAD, session resumption, everything) and point it at SpeechRouter.
The gateway adds your SpeechRouter key, billing, limits and logs, and uses
our provider account (or [your own key](/guides/byok/)).

| Models | Endpoint | Client |
| --- | --- | --- |
| `openai/gpt-realtime-2.1`, `-2.1-mini`, `-2`, `-1.5`, `gpt-realtime`, `-mini` | `wss://api.speechrouter.ai/v1/realtime?model=…` | OpenAI SDKs, Agents SDK |
| `gemini/gemini-3.8-live`, `-extended-thinking`, `gemini-2.5-flash-native-audio-preview-12-2025` | `wss://api.speechrouter.ai/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent` | `google-genai` |

Catalog entries have `"kind": "live"` and a `dialect` saying which protocol they speak.

## OpenAI Realtime

```python
from openai import AsyncOpenAI

client = AsyncOpenAI(api_key="sk_sr_...", base_url="https://api.speechrouter.ai/v1")
async with client.realtime.connect(model="openai/gpt-realtime-2.1") as conn:
    await conn.session.update(session={"type": "realtime", "instructions": "Be brief."})
    await conn.input_audio_buffer.append(audio=b64_pcm16_24k)
    await conn.response.create()
    async for event in conn:
        if event.type == "response.done":
            break
```

The bare model name (`model=gpt-realtime-2.1`) works too. The model is fixed
for the connection: a `session.update` naming another model is rejected with
an `error` event.

**Browsers:** mint a short-lived token on your server. Either use
[`POST /v1/tokens`](/reference/rest/#post-v1tokens), or OpenAI's shape at
`POST /v1/realtime/client_secrets` (returns `{"value": "st_…"}`). Then
connect with the subprotocols `["realtime", "openai-insecure-api-key.st_…"]`,
exactly as with OpenAI. WebRTC and SIP are not proxied; use WebSocket.

## Gemini Live

```python
from google import genai
from google.genai import types

client = genai.Client(
    api_key="sk_sr_...",
    http_options=types.HttpOptions(base_url="https://api.speechrouter.ai", api_version="v1beta"),
)
config = types.LiveConnectConfig(response_modalities=[types.Modality.AUDIO])
async with client.aio.live.connect(model="gemini-3.8-live", config=config) as session:
    await session.send_realtime_input(audio=types.Blob(data=pcm16_16k, mime_type="audio/pcm;rate=16000"))
    async for message in session.receive():
        ...
```

Your SpeechRouter key or `st_` token goes wherever the SDK puts a Gemini key
(`x-goog-api-key`, `?key=`, `?access_token=`, or `Authorization: Token`).
The model comes from the `setup` message; the gateway reads it, checks it, and
forwards it unchanged. Connections last about 10 minutes upstream (`goAway`);
resume with the session handle on a new connection, as usual.

## Errors

Errors arrive the way the vendor SDK expects them:

- **OpenAI:** an `error` event (`error.code` is a [SpeechRouter code](/reference/errors/),
  e.g. `auth_failed`, `insufficient_credits`), then close `1008`.
- **Gemini:** close `1008` with reason `"<code>: <message>"`.

Provider events and close codes pass through untouched, with one exception.
On SpeechRouter's own provider account, messages about that account (quota,
billing, keys) are replaced with a generic message, and our team is alerted.

## Limits

| Limit | Default |
| --- | --- |
| Concurrent live sessions per org | 5 (separate from streaming STT) |
| Minimum balance to start | $5 (not applied with BYOK) |
| Session length | 60 min |
| Idle (no frames either way) | 120 s |
| Mid-session credit check | every 30 s |

## Billing

Live sessions bill per token by modality, exactly as the provider reports
them (text/audio/image input, cached input, text/audio output), at list
price. OpenAI's optional input transcription is billed separately by OpenAI,
and appears as its own line on the transcription model. Usage is recorded
every 60 seconds, so long sessions show up while they run. See
[Pricing](/guides/pricing/).
