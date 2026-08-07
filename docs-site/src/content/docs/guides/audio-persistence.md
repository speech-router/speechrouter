---
title: Audio persistence
description: Opt-in session recording for compliance, QA, or dispute resolution — self-hosted only, off by default everywhere.
---

SpeechRouter's core promise is that audio passes straight through to the
provider and nothing else ever sees it — that's true for the hosted
`api.speechrouter.ai` unconditionally, and it's the default for self-hosted
gateways too. If you have a genuine reason to keep a copy of session audio —
compliance, QA review, dispute resolution — you can opt in on your own
self-hosted deployment. It is never available on the hosted service.

## Enabling it

```bash
SPEECHROUTER_AUDIO_SINK=s3
SPEECHROUTER_AUDIO_SINK_BUCKET=your-bucket
SPEECHROUTER_AUDIO_SINK_PREFIX=recordings        # optional
```

Credentials and region default to the same `SPEECHROUTER_AWS_*` variables
used for the AWS Transcribe provider. Set the `_AUDIO_SINK_` variants only
if recordings should go to a different account, bucket, or region:

| Variable | Default | Meaning |
| --- | --- | --- |
| `SPEECHROUTER_AUDIO_SINK` | `none` | `none` \| `s3` |
| `SPEECHROUTER_AUDIO_SINK_BUCKET` | — | Required when `s3` |
| `SPEECHROUTER_AUDIO_SINK_PREFIX` | — | Optional key prefix, e.g. `recordings` |
| `SPEECHROUTER_AUDIO_SINK_REGION` | `SPEECHROUTER_AWS_REGION` | Override if different from Transcribe's region |
| `SPEECHROUTER_AUDIO_SINK_ACCESS_KEY` | `SPEECHROUTER_AWS_ACCESS_KEY_ID` | Override for a separate account |
| `SPEECHROUTER_AUDIO_SINK_SECRET_KEY` | `SPEECHROUTER_AWS_SECRET_ACCESS_KEY` | Override for a separate account |

Your IAM policy needs `s3:PutObject` (and `s3:AbortMultipartUpload` for
cleanup on error paths) on the bucket.

## What gets stored

One object per session, at `{prefix}/{session_id}.raw` — the raw audio
bytes exactly as received, in whatever encoding and sample rate the session
declared. Raw PCM isn't self-describing on its own; a consumer that needs a
playable file prepends a WAV header using the session's known encoding/rate.

## How it's written

Streamed via real S3 multipart upload as audio arrives — buffered only up
to S3's 5&nbsp;MB minimum part size per in-flight part, never a whole
session. A long session or many concurrent sessions never spikes gateway
memory. Sessions under 5&nbsp;MB total skip multipart entirely and land as
a single `PutObject`.

A sink failure **never breaks transcription** — write errors are logged,
not raised into the session, and a failed multipart upload is aborted
server-side rather than left as an orphaned (and billed) incomplete upload.

## Building your own sink

`SPEECHROUTER_AUDIO_SINK=s3` ships in the box, but the hook itself is a
two-method interface:

```python
class AudioSink(Protocol):
    async def on_chunk(self, session_id: str, chunk: bytes) -> None: ...
    async def on_session_end(self, session_id: str) -> None: ...
```

Anything satisfying that — write to local disk, a different object store,
a message queue — plugs in the same way; see
`speechrouter_gateway/audio/sink.py` and `s3_sink.py` for the reference
shape.
