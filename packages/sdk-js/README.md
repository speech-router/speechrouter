# speechrouter

One API for every speech model — [speechrouter.ai](https://speechrouter.ai).

This is a placeholder release; the official SDK (streaming WebSocket client with
mid-stream failover events + batch) lands here next.

**Works today** — batch via any OpenAI SDK:

```js
import OpenAI from "openai";
const client = new OpenAI({ baseURL: "https://api.speechrouter.ai/v1", apiKey: "sk_sr_..." });
const t = await client.audio.transcriptions.create({ model: "deepgram/nova-3", file });
```

Streaming: `wss://api.speechrouter.ai/v1/listen?model=deepgram/nova-3&fallbacks=soniox/stt-rt-v5`
