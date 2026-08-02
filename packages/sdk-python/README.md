# speechrouter

One API for every speech model — [speechrouter.ai](https://speechrouter.ai).

Async Python SDK: streaming speech-to-text over WebSocket with mid-stream
provider failover, plus batch transcription.

```sh
pip install "git+https://github.com/speech-router/speechrouter.git#subdirectory=packages/sdk-python"
# (PyPI package coming soon — the name is pending approval)
```

## Streaming

```python
import asyncio
from speechrouter import SpeechRouter, Transcript

async def main():
    sr = SpeechRouter(api_key="sk_sr_...")

    async with sr.listen(
        model="deepgram/nova-3",
        fallbacks=["soniox/stt-rt-v5"],   # dies mid-stream? we switch, you keep captioning
    ) as stream:
        async def feed():
            for chunk in pcm_chunks():     # 16-bit linear PCM, 16 kHz mono by default
                await stream.send_audio(chunk)

        feeder = asyncio.create_task(feed())
        async for event in stream:
            if isinstance(event, Transcript) and event.is_final:
                print(event.text)

        await feeder
        done = await stream.stop()         # finalize → transcript tail → usage
        print(done.usage)

asyncio.run(main())
```

Every event is a typed dataclass mirroring the wire protocol: `Transcript`
(with `words`, speaker labels, `provider_raw`), `ProviderSwitched`,
`SpeechStarted`, `UtteranceEnd`, `Done`, …

## Batch

```python
result = await sr.transcribe(model="cartesia/ink-whisper", file=open("meeting.wav", "rb"))
print(result["text"])

# subtitles straight out:
srt = await sr.transcribe(model="deepgram/nova-3", file=audio_bytes, response_format="srt")
```

Pass `url=` instead of `file=` to have the gateway fetch the audio itself.

## Models

```python
models = await sr.list_models()   # slugs, capabilities, live pricing
```

## Errors

Everything raises `SpeechRouterError` with a machine-readable `code`
(`insufficient_credits`, `concurrency_exceeded`, `provider_error`, …), the
upstream `provider` when known, and a `recoverable` hint.

## Self-hosting

```python
SpeechRouter(api_key="...", base_url="http://localhost:8080")
```

Apache-2.0 · [protocol spec](https://github.com/speech-router/speechrouter/tree/main/packages/spec) · [gateway](https://github.com/speech-router/speechrouter)
