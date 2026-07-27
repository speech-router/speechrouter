# Azure AI Speech — protocol brief (verified 2026-07-27)

## Realtime: Speech SDK is the only supported path
- SDK speaks proprietary undocumented WS (USP) to `wss://<region>.stt.speech.microsoft.com`. SDK-free realtime = reverse-engineering (JS SDK is de-facto reference). **Decision: use `azure-cognitiveservices-speech` + PushAudioInputStream** (wraps a C lib, acceptable).
- Voice Live API is documented WS but token-billed (~10 tok/s), 60-min cap, agent-oriented — wrong fit for STT proxy.
- Push stream: **PCM s16le mono 8k/16k only**. `AudioStreamFormat(16000,16,1)` → PushAudioInputStream → AudioConfig; `push.close()` = EOS. Compressed via GStreamer.
- Continuous: start_continuous_recognition_async; events `recognizing` (partials) / `recognized` (finals) / `canceled` / session_*. Segmentation: `Speech_SegmentationSilenceTimeoutMs` (100–5000, def 500), `Speech_SegmentationStrategy="Semantic"` (SDK ≥1.41).
- **Word timestamps: FINALS ONLY** — `request_word_level_timestamps()`, parse `result.json` → `NBest[0].Words[{Word, Offset, Duration}]`.
- **Timestamps = 100-ns ticks (÷10^7 = seconds)**. EXCEPTION: fast transcription REST uses milliseconds.
- Diarization: `transcription.ConversationTranscriber`, speaker_id "Guest-1"... ("Unknown" early), intermediate IDs need `DiarizeIntermediateResults=true`, **240-min session cap**.
- Language ID: AutoDetectSourceLanguageConfig (≤4 at-start, ≤10 continuous; continuous needs `/speech/universal/v2` endpoint + LanguageIdMode=Continuous).
- Phrase lists: PhraseListGrammar.addPhrase, ≤500, weight 0–2.

## Fast transcription REST (SDK-free batch-ish fallback)
`POST {endpoint}/speechtotext/transcriptions:transcribe?api-version=2025-10-15` — sync, multipart (audio|audioUrl + definition JSON: locales, diarization{maxSpeakers 2–35 mono-only}, channels ≤2, phraseList{biasingWeight}). <5h, <500MB. Response ms-based: combinedPhrases[], phrases[{channel, speaker, offsetMilliseconds, words[]}].

## Batch
`POST .../speechtotext/transcriptions:submit?api-version=2025-10-15` (v3.x RETIRED 2026-03-31). contentUrls (≤1000 SAS) | contentContainerUrl (≤10k). properties: **timeToLiveHours REQUIRED** (6h–31d), wordLevelTimestampsEnabled, diarization.maxCount <36, languageIdentification.candidateLocales 2–10, destinationContainerUrl (MUST be inside properties — root placement silently ignored). Poll self URI or webhooks. 1 GB/file.

## Auth / limits / pricing
- `Ocp-Apim-Subscription-Key` or STS token (POST /sts/v1.0/issueToken, **valid 10 min** — refresh ~9). Entra: `aad#<resourceId>#<token>`.
- Concurrency: 100 (S0, adjustable; F0=1). 429s during autoscale — ramp ~20 conns/90–120s.
- Billed per audio hour; $/hr renders client-side, **unverified (~$1/hr cited)** — check pricing page in browser before catalog entry.
