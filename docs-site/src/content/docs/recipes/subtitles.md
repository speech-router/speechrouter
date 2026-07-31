---
title: Generate subtitles
description: File in, ready-to-serve SRT or VTT out — one request.
---

The batch endpoint emits subtitle formats directly — no timestamp math, no
post-processing:

```bash
curl -s https://api.speechrouter.ai/v1/audio/transcriptions \
  -H "Authorization: Bearer $SPEECHROUTER_API_KEY" \
  -F model=openai/whisper-1 \
  -F response_format=srt \
  -F file=@episode.mp3 > episode.srt
```

Swap `srt` for `vtt` for the web-native format:

```html
<video controls src="/episode.mp4">
  <track default kind="captions" src="/episode.vtt" srclang="en" />
</video>
```

## Model choice

Any batch model works; the difference is timing granularity:

- **Word-timestamp models** (`openai/whisper-1`, `assemblyai/universal-2`,
  `speechmatics/*`, `elevenlabs/scribe_v2`, `groq/whisper-large-v3`) cue
  subtitles at word precision.
- Models without word timing degrade to one cue per utterance — fine for
  short clips, rough for long-form.

## Speaker-labeled captions

Want `[SPEAKER 1]` prefixes? Request `verbose_json` with `diarization=true`
and template your own cues from `words[]` — speakers arrive as integers:

```bash
curl -s … -F model=assemblyai/universal-2 -F diarization=true \
  -F response_format=verbose_json -F file=@panel.mp3 \
  | jq -r '.words[] | "\(.speaker)\t\(.start)\t\(.word)"'
```

## Long files

Up to 250 MB per request. For feature-length audio, `mistral/voxtral-mini`
accepts up to 3 hours in one shot at $0.003/min.
