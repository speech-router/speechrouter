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

## MAI-Transcribe (docs read 2026-09-23) — batch only
Sources: learn.microsoft.com `azure/ai-services/speech-service/mai-transcribe` (MicrosoftDocs/azure-ai-docs `mai-transcribe.md` @ 7017caf, 2026-09-10; the 1.5-era text is @ 0c1e1c1, 2026-07-21), `llm-speech` + its REST include (sample response), `regions?tabs=llmspeech`, `includes/language-support/mai-transcribe.md`. Prices: `data-amount` attributes on azure.microsoft.com/pricing/details/speech (the page renders `$-` client-side) and the pricing-calculator JSON (`speech-services-mai-transcribe-2-speech-to-text`). **Not yet live-verified**: see Open.

Microsoft AI's in-house STT. Not a new API: the **fast transcription endpoint above** with an `enhancedMode` block naming the model ("LLM Speech" is the same switch with `task`/`prompt` instead of `model`). Same key, same `Ocp-Apim-Subscription-Key` header, same multipart `audio` + `definition`, same `TranscribeResult` response (ms units). Preview.

| Model (`enhancedMode.model`) | Status | Diarization | Word timings | Style | Price |
|---|---|---|---|---|---|
| `MAI-Transcribe-2` | preview, 60 langs | `diarization.enabled` | `modelOptions.timestamps` | `modelOptions.transcribeStyle`, default `verbatim` | **$0.10/hr** — "limited-time promotional offer till 12/31/2026" (usgov $0.125) |
| `mai-transcribe-1.5` | preview, 43 langs | **none** | undocumented | `enhancedMode.transcribeStyle` (not under modelOptions), default readability; `verbatim` opt-in | $0.36/hr (= fast transcription) |
| `mai-transcribe-1` | **deprecated 2026-08-20** | — | — | — | not added |

```
POST https://<resource>.cognitiveservices.azure.com/speechtotext/transcriptions:transcribe?api-version=2025-10-15
Ocp-Apim-Subscription-Key: <key>
audio=@file.wav
definition={"enhancedMode":{"enabled":true,"model":"MAI-Transcribe-2","modelOptions":{"timestamps":"word","transcribeStyle":"clean"}},
            "diarization":{"enabled":true},"phraseList":{"phrases":["Contoso"]},"locales":["en"]}
```

- `enhancedMode.enabled: true` + `enhancedMode.model` are both required. Pricing footnote: "When using MAI-Transcribe, Standard-Audio pricing applies."
- **Word timings are opt-in on MAI-2**: `modelOptions.timestamps` = `word` | `segment` | `none`, **default `none`**. `segment` partitions by language (and speaker when diarizing). Adapter sends `word`.
- `transcribeStyle`: `verbatim` keeps fillers/false starts; `clean` removes them.
- `locales`: **one bare language code** (`"en"`, `"yue"`, `"fil"`), a "very strong hint" — omit for auto-detect (the default; code-switching is automatic). Adapter maps `en-US` → `en`, drops `auto`.
- `phraseList.phrases`: keyword biasing, hints not forced output. MAI docs show no `biasingWeight`; adapter omits it. Forgebook notebook (1.5) says up to 200 phrases; Learn gives no cap.
- Diarization (MAI-2): `{"enabled": true}` — docs show no `maxSpeakers`. **Preview limit: recordings of ~15 min or longer fail** with 408 `Timeout`, 500, or 503 `diarization_unavailable`; the same audio works with diarization off. Speakers come back as int `phrases[].speaker`.
- Response: `TranscribeResult` exactly as fast transcription (`durationMilliseconds`, `combinedPhrases[].text`, `phrases[{offsetMilliseconds, durationMilliseconds, text, words?, locale, speaker?, confidence}]`). In enhanced mode `confidence` is always 0. Sample locales come back lowercase (`en-us`).
- Audio: WAV, MP3, FLAC. REST reference: audio <2 h and <250 MB (older MAI text: <300 MB). Catalog `max_audio_seconds` = 7200.
- Regions (llmspeech tab, "Transcribe with MAI-Transcribe"): centralindia, eastus, northeurope, southeastasia, westus, westus2. Needs a **Microsoft Foundry resource** (kind AIServices).
- Also usable as `input_audio_transcription.model: "mai-transcribe"` inside Voice Live — token-billed agent sessions, same reason as above for not using it as a streaming STT path.

### Mapping
- Slugs `azure/mai-transcribe-2`, `azure/mai-transcribe-1.5` on the existing `azure` batch provider (same credentials, same endpoint builder).
- `provider_params` are deep-merged into the definition (nested objects merge), then the adapter re-asserts `enhancedMode.enabled/model` — the model decides the vendor meter. On `azure/fast-transcription`, a passed `enhancedMode.model` is stripped for the same reason (LLM Speech `task`/`prompt` pass through; they share fast transcription's SKU).
- `diarization=true` on 1.5 is ignored (the OpenAI non-diarize-model precedent); the catalog says `diarization: false`.
- No `hipaa_eligible` flag: preview features, compliance scope unverified.

### Open (verify live)
- `modelOptions` placement: the feature table labels it `modelOptions.timestamps` (top level?), every wire example nests it in `enhancedMode`. We follow the examples.
- Model-id casing: 1.5 examples are lowercase `mai-transcribe-1.5`, the current list says `MAI-Transcribe-1.5`; MAI-2 only appears capitalized. Is it case-insensitive?
- Does the regional host (`https://<region>.api.cognitive.microsoft.com`, which our adapter uses) serve enhanced mode, or only the resource subdomain the docs show? Does an old `SpeechServices`-kind resource work?
- Does 1.5 return `words[]` at all? Catalog says no word timings until seen.
- What an unsupported region / unknown model returns (status + `innerError.code`).
- MAI-2 price after 2026-12-31.
