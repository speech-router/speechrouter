# AWS Transcribe Streaming — protocol brief (verified 2026-07-27)

## RAW WEBSOCKET IS OFFICIALLY DOCUMENTED & RECOMMENDED FOR US
- boto3: batch only. `amazon-transcribe` (awslabs): **DEPRECATED** (high-CPU warning). `aws-sdk-transcribe-streaming`: 0.x, py≥3.12. → **own ~100-line event-stream codec over raw WS** (we already have this: aws_signer.py + evenstream.py).
- `wss://transcribestreaming.<region>.amazonaws.com:8443/stream-transcription-websocket` — SigV4 **presigned GET URL** (canonical headers = host only, empty-string payload hash, X-Amz-Expires **max 300s** — bounds handshake only). Service params in same query: language-code, media-encoding, sample-rate, show-speaker-label, enable-partial-results-stabilization, partial-results-stability, vocabulary-name, session-id. IAM: transcribe:StartStreamTranscriptionWebSocket. NO per-chunk signing on WS.

## Event-stream framing (binary frames)
prelude: 4B BE total len + 4B BE headers len + 4B prelude CRC32; headers [1B name-len][name][1B type(7=STRING)][2B val-len][val]; payload; 4B message CRC32. Audio msg headers: `:message-type=event`, `:event-type=AudioEvent`, `:content-type=application/octet-stream`. **End of stream = empty-payload AudioEvent.** Errors: `:message-type=exception` + `:exception-type` header (BadRequest/InternalFailure/LimitExceeded/UnrecognizedClient) then close.

## Audio + results
- MediaEncoding: exactly `pcm | ogg-opus | flac`; PCM = s16le raw ("does not include WAV"). Sample rate 8000–48000 (16k rec). **Chunks 50–200ms uniform** (32KB cap is folklore, not in docs). Send zero-byte silence during gaps (billed) — **idle timeout ~15s**.
- TranscriptEvent: {Transcript:{Results:[{ResultId, StartTime, EndTime, IsPartial, ChannelId, LanguageCode, Alternatives:[{Transcript, Items[], Entities[]}]}]}}
- **ResultId stable across all partials of a segment** — key replace-in-place on it. Item: {Content, Type: pronunciation|punctuation, StartTime/EndTime **seconds as JSON doubles** (batch uses strings!), Confidence, Stable, Speaker, VocabularyFilterMatch}. Word timing on EVERY item incl. partials.
- Stabilization: EnablePartialResultsStabilization + PartialResultsStability high|medium|low → per-Item `Stable`. Caveat: can change FINAL content.
- Diarization: show-speaker-label → Speaker spk_0..spk_29 (max 30, no max param). Channels: EnableChannelIdentification + NumberOfChannels (must be 2).
- Language ID: exactly one of LanguageCode | IdentifyLanguage (+LanguageOptions, one dialect/lang) | IdentifyMultipleLanguages.
- **NEW: SessionResumeWindow** (x-amzn-transcribe-session-resume-window, 1–300 min) — reconnect to same session after drop; 409 ConflictException on session-id reuse.

## Limits / pricing
- 25 concurrent streams/region default (adjustable); **~4h hard session cap** (removed from docs but enforced — rotate); idle ~15s.
- Pricing (Price List API, June 2026): streaming **$0.01/min FLAT** (old tiers gone), **15-SECOND MINIMUM per request** (short reconnects cost!), batch $0.006/min. Medical streaming $0.075/min. Regions: us-east-1/2, us-west-2, eu-west-1/2, eu-central-1/2, ap-*, NOT us-west-1/eu-west-3.

## Batch
StartTranscriptionJob: unique name, s3:// Media, formats incl. wav here. OutputBucketName or service bucket presigned URI. Items have STRING start_time/end_time (unlike streaming doubles). ShowSpeakerLabels + MaxSpeakerLabels ≤30. 8h/2GB, 250 concurrent jobs.
