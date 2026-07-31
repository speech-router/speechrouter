// GENERATED from gateway providers/*/params.json — do not edit.
// Regenerate: python3 scripts/gen_provider_params.py

/** Provider-specific options for `assemblyai/*` models. */
export interface AssemblyaiParams {
  /** Confidence needed to declare end of turn — @default 0.4; range 0–1; applies to streaming */
  end_of_turn_confidence_threshold?: number
  /** Minimum silence (ms) before a turn can end — applies to streaming */
  min_turn_silence?: number
  /** Silence (ms) that forces end of turn — applies to streaming */
  max_turn_silence?: number
  /** Voice-activity detection sensitivity — applies to streaming */
  vad_threshold?: number
  /** Emit partials continuously instead of on change — @default false; applies to streaming */
  continuous_partials?: boolean
  /** Cap for streaming diarization — applies to streaming */
  max_speakers?: number
  /** Auto-detect the spoken language — @default false; applies to streaming + batch */
  language_detection?: boolean
  /** Domain-tuned recognition — applies to streaming */
  domain?: 'medical-v1'
  /** Free-text context to bias recognition — applies to streaming */
  prompt?: string
  /** Redact personally identifiable information — @default false; applies to streaming + batch */
  redact_pii?: boolean
  /** Close the vendor session after this many silent seconds — range 5–3600; applies to streaming */
  inactivity_timeout?: number
  /** universal-3-5-pro: latency/accuracy preset — applies to streaming */
  mode?: 'max_accuracy' | 'balanced' | 'min_latency'
  [key: string]: unknown
}

/** Provider-specific options for `aws/*` models. */
export interface AwsParams {
  [key: string]: unknown
}

/** Provider-specific options for `azure/*` models. */
export interface AzureParams {
  /** Candidate locales for language identification — applies to batch */
  locales?: unknown[]
  /** {maxSpeakers: 2–35} — mono audio only — applies to batch */
  diarization?: Record<string, unknown>
  /** Channel indices to transcribe (≤2) — applies to batch */
  channels?: unknown[]
  [key: string]: unknown
}

/** Provider-specific options for `cartesia/*` models. */
export interface CartesiaParams {
  /** ink-2: confidence to open a turn — @default 0.8; applies to streaming */
  turn_start_threshold?: number
  /** ink-2: early end-of-turn signal for LLM head-start — @default 0.4; applies to streaming */
  turn_eager_end_threshold?: number
  /** ink-2: confidence to close a turn — @default 0.2; applies to streaming */
  turn_end_threshold?: number
  /** ink-2: force turn end after this silence — @default 5600; applies to streaming */
  turn_end_timeout_ms?: number
  /** ink-whisper: ignore audio below this volume — applies to streaming */
  min_volume?: number
  /** ink-whisper: silence tolerated before finalizing — applies to streaming */
  max_silence_duration_secs?: number
  [key: string]: unknown
}

/** Provider-specific options for `deepgram/*` models. */
export interface DeepgramParams {
  /** Format numbers, dates, currency in the transcript — @default false; applies to streaming + batch */
  smart_format?: boolean
  /** Add punctuation and capitalization — @default false; applies to streaming + batch */
  punctuate?: boolean
  /** Silence (ms) before the endpointer fires — @default 10; applies to streaming */
  endpointing?: number
  /** Gap (ms) that triggers UtteranceEnd; needs interim results on — range 1000–…; applies to streaming */
  utterance_end_ms?: number
  /** Emit speech-started events from the voice-activity detector — @default false; applies to streaming */
  vad_events?: boolean
  /** Diarization model variant (replaces the deprecated diarize flag) — applies to streaming + batch */
  diarize_model?: string
  /** Transcribe each audio channel independently — @default false; applies to streaming + batch */
  multichannel?: boolean
  /** word:boost pairs — nova-2 family only (nova-3 uses keyterms) — applies to streaming + batch */
  keywords?: string
  /** Flux models: end-of-turn confidence threshold — @default 0.7; range 0.5–0.9; applies to streaming */
  eot_threshold?: number
  /** Flux models: earlier, lower-confidence end-of-turn signal — range 0.3–0.9; applies to streaming */
  eager_eot_threshold?: number
  /** Flux models: force end-of-turn after this silence — @default 5000; applies to streaming */
  eot_timeout_ms?: number
  [key: string]: unknown
}

/** Provider-specific options for `elevenlabs/*` models. */
export interface ElevenlabsParams {
  /** When transcripts commit: on silence (vad) or on demand — applies to streaming */
  commit_strategy?: 'manual' | 'vad'
  /** Voice-activity sensitivity for vad commits — applies to streaming */
  vad_threshold?: number
  /** Silence that triggers a vad commit — applies to streaming */
  vad_silence_threshold_secs?: number
  /** Additional expected languages — applies to streaming */
  secondary_languages?: unknown[]
  /** Clean up disfluencies — @default false; applies to streaming */
  no_verbatim?: boolean
  /** Suppress non-speech audio — @default false; applies to streaming */
  filter_background_audio?: boolean
  /** false = zero-retention mode at ElevenLabs — @default true; applies to streaming */
  enable_logging?: boolean
  /** Expected speaker count for diarization — range …–32; applies to batch */
  num_speakers?: number
  /** Timestamp detail level — applies to batch */
  timestamps_granularity?: 'none' | 'word' | 'character'
  /** Mark laughter, applause, and other audio events — @default false; applies to batch */
  tag_audio_events?: boolean
  /** Detect 65 entity types (extra vendor charge) — @default false; applies to batch */
  entity_detection?: boolean
  /** Label agent/customer roles — @default false; applies to batch */
  detect_speaker_roles?: boolean
  [key: string]: unknown
}

/** Provider-specific options for `google/*` models. */
export interface GoogleParams {
  [key: string]: unknown
}

/** Provider-specific options for `groq/*` models. */
export interface GroqParams {
  /** Context/spelling hints (≤224 tokens) — applies to batch */
  prompt?: string
  /** Sampling temperature — range 0–1; applies to batch */
  temperature?: number
  /** With verbose output — applies to batch */
  'timestamp_granularities[]'?: 'word' | 'segment'
  [key: string]: unknown
}

/** Provider-specific options for `mistral/*` models. */
export interface MistralParams {
  /** Up to 100 bias terms (English-optimized) — applies to batch */
  context_bias?: unknown[]
  /** Timestamp detail level — applies to batch */
  timestamp_granularities?: 'word' | 'segment'
  /** Latency target for realtime partials — @default 800; applies to streaming */
  target_streaming_delay_ms?: number
  [key: string]: unknown
}

/** Provider-specific options for `openai/*` models. */
export interface OpenaiParams {
  /** Context/spelling hints for the transcription — applies to batch */
  prompt?: string
  /** Sampling temperature — range 0–1; applies to batch */
  temperature?: number
  /** whisper-1 with verbose output only — applies to batch */
  'timestamp_granularities[]'?: 'word' | 'segment'
  /** Required by the diarize model for audio over 30s ("auto") — applies to batch */
  chunking_strategy?: string
  /** Diarize model: enroll up to 4 named speakers — applies to batch */
  'known_speaker_names[]'?: unknown[]
  /** Reference audio for enrolled speakers — applies to batch */
  'known_speaker_references[]'?: unknown[]
  /** gpt-realtime-whisper: latency/quality knob — applies to streaming */
  delay?: 'minimal' | 'low' | 'medium' | 'high' | 'xhigh'
  /** server_vad {threshold, silence_duration_ms} or semantic_vad {eagerness} — applies to streaming */
  turn_detection?: Record<string, unknown>
  [key: string]: unknown
}

/** Provider-specific options for `soniox/*` models. */
export interface SonioxParams {
  /** Restrict recognition to the hinted languages — @default false; applies to streaming + batch */
  language_hints_strict?: boolean
  /** Tag tokens with the detected language — @default false; applies to streaming + batch */
  enable_language_identification?: boolean
  /** Upper bound on endpoint latency — @default 2000; range 500–3000; applies to streaming */
  max_endpoint_delay_ms?: number
  /** Endpoint eagerness; docs suggest 0.3 for voice agents — range -1–1; applies to streaming */
  endpoint_sensitivity?: number
  /** Latency/accuracy trade for endpoint detection (2 = voice-agent preset) — range 0–3; applies to streaming */
  endpoint_latency_adjustment_level?: number
  /** Domain context: general text, terms, translation_terms (≤8k tokens) — applies to streaming + batch */
  context?: Record<string, unknown>
  /** Live translation config (one_way or two_way) — applies to streaming */
  translation?: Record<string, unknown>
  /** Your correlation id, echoed in Soniox logs — applies to streaming + batch */
  client_reference_id?: string
  [key: string]: unknown
}

/** Provider-specific options for `speechmatics/*` models. */
export interface SpeechmaticsParams {
  /** Max seconds before a final is emitted — @default 4; range 0.7–4; applies to streaming */
  max_delay?: number
  /** Whether max_delay may stretch to finish entities — applies to streaming */
  max_delay_mode?: 'flexible' | 'fixed'
  /** {max_speakers, speaker_sensitivity, prefer_current_speaker} — applies to streaming + batch */
  speaker_diarization_config?: Record<string, unknown>
  /** [{content, sounds_like[]}] — up to 1000 entries with pronunciations — applies to streaming + batch */
  additional_vocab?: unknown[]
  /** Emit typed entities (numbers, dates) in results — @default true; applies to streaming + batch */
  enable_entities?: boolean
  /** Tune permitted marks and sensitivity — applies to streaming + batch */
  punctuation_overrides?: Record<string, unknown>
  /** {end_of_utterance_silence_trigger: 0–2s} — must be < max_delay — applies to streaming */
  conversation_config?: Record<string, unknown>
  [key: string]: unknown
}

/** Map from provider name to its typed params. */
export interface ProviderParamsMap {
  assemblyai: AssemblyaiParams
  aws: AwsParams
  azure: AzureParams
  cartesia: CartesiaParams
  deepgram: DeepgramParams
  elevenlabs: ElevenlabsParams
  google: GoogleParams
  groq: GroqParams
  mistral: MistralParams
  openai: OpenaiParams
  soniox: SonioxParams
  speechmatics: SpeechmaticsParams
}
