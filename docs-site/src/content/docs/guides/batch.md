---
title: Batch transcription
description: POST /v1/audio/transcriptions — files or URLs, five output formats.
---

`POST https://api.speechrouter.ai/v1/audio/transcriptions` — multipart form,
OpenAI-compatible shape.

## Form fields

| Field | Default | Meaning |
| --- | --- | --- |
| `model` | *(required)* | Model slug with `batch` mode, e.g. `openai/whisper-1` |
| `file` | — | The audio (up to 250 MB). Exactly one of `file` / `url` |
| `url` | — | Public URL the gateway fetches instead |
| `response_format` | `json` | `json` · `verbose_json` · `srt` · `vtt` · `text` |
| `language` | auto | Language hint |
| `diarization` | `false` | Speaker labels ([model support varies](/providers/)) |
| `keyterms` | — | Comma-separated bias terms |
| `provider_params` | — | JSON object string, passed through to the vendor |
| `include_raw` | `false` | Include the raw provider payload (`verbose_json`) |

## Output formats

- **`json`** — `{ "text": "…" }`, nothing else. The pipe-into-jq format.
- **`verbose_json`** — text plus `words[]` (timings, confidence, speakers),
  duration, language, and `provider_raw` when requested.
- **`srt` / `vtt`** — ready-to-serve subtitle files.
- **`text`** — the bare transcript.

```bash
curl -s https://api.speechrouter.ai/v1/audio/transcriptions \
  -H "Authorization: Bearer $SPEECHROUTER_API_KEY" \
  -F model=speechmatics/melia-1 \
  -F response_format=verbose_json \
  -F file=@interview.mp3 | jq '.words[:3]'
```

:::note[Speaker labels]
With `diarization=true`, models that return word-level speakers give you
`words[].speaker` as integers. Models that diarize at segment level (e.g.
`openai/gpt-4o-transcribe-diarize`) return one word entry per speaker turn.
:::

## Timeouts & sizes

Uploads and remote URLs are capped at **250 MB**. Batch requests hold the
connection until the provider finishes — allow up to 10 minutes for very long
audio in your HTTP client timeout.
