---
title: Python
description: The speechrouter package — async client for Python ≥ 3.10.
---

```bash
pip install speechrouter
```

Async-first (`httpx` + `websockets`).

## Client

```python
from speechrouter import SpeechRouter

sr = SpeechRouter(api_key=os.environ["SPEECHROUTER_API_KEY"])
# self-hosted: SpeechRouter(api_key=..., base_url="https://gateway.internal")
```

## Batch

```python
with open("meeting.wav", "rb") as f:
    result = await sr.transcribe(model="openai/whisper-1", file=f)
print(result["text"])

# URL input + subtitles out
srt = await sr.transcribe(
    model="assemblyai/universal-2",
    url="https://example.com/podcast.mp3",
    response_format="srt",
)
```

## Streaming

```python
async with sr.listen(
    model="soniox/stt-rt-v5",
    fallbacks=["deepgram/nova-3"],
    sample_rate=16000,
) as stream:
    asyncio.create_task(feed_microphone(stream))   # stream.send_audio(pcm)

    async for event in stream:
        match event["type"]:
            case "transcript" if event["is_final"]:
                print(event["text"])
            case "utterance_end":
                await agent.respond()
```

`await stream.finalize()` flushes finals and resolves when the gateway sends
`done`. Keepalives on idle sockets are automatic (`keepalive=8.0`).

## Tokens & models

```python
token = await sr.create_token(ttl_seconds=60)   # for browser/mobile clients
models = await sr.list_models()                  # live catalog with prices
```

## Errors

Failures raise `SpeechRouterError` carrying the gateway's
[stable code](/reference/errors/).
