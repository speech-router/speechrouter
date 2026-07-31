/* Wire types — mirrors packages/spec/events.schema.json (the protocol's
 * source of truth). Field names stay snake_case: what the socket carries is
 * what you type against. */

export type ErrorCode =
  | 'auth_failed'
  | 'key_revoked'
  | 'insufficient_credits'
  | 'rate_limited'
  | 'concurrency_exceeded'
  | 'invalid_request'
  | 'model_not_found'
  | 'unsupported_capability'
  | 'unsupported_encoding'
  | 'payload_too_large'
  | 'provider_error'
  | 'provider_timeout'
  | 'all_providers_failed'
  | 'audio_timeout'
  | 'session_expired'
  | 'internal_error'

export interface Word {
  w: string
  start: number
  end: number
  conf?: number
  speaker?: number
  lang?: string
}

export interface SessionOpenEvent {
  type: 'session.open'
  session_id: string
  model: string
  encoding?: string
  sample_rate?: number
}

export interface TranscriptEvent {
  type: 'transcript'
  is_final: boolean
  text: string
  words?: Word[]
  start?: number
  end?: number
  lang?: string
  /** Present when the session was opened with includeRaw. */
  provider_raw?: Record<string, unknown>
}

export interface SpeechStartedEvent {
  type: 'speech_started'
  at: number
}

export interface UtteranceEndEvent {
  type: 'utterance_end'
  at: number
}

export interface ProviderSwitchedEvent {
  type: 'provider_switched'
  from: string
  to: string
  resumed_at: number
  speaker_mapping_preserved: boolean
}

export interface TextDeltaEvent {
  type: 'text.delta'
  text: string
}

export interface ClearedEvent {
  type: 'cleared'
  last_seq: number
}

export interface KeepAliveEvent {
  type: 'keepalive'
}

export interface DoneEvent {
  type: 'done'
  usage: {
    audio_seconds?: number
    model?: string
    [key: string]: unknown
  }
}

export interface ErrorEvent {
  type: 'error'
  code: ErrorCode
  message: string
  provider?: string
  recoverable?: boolean
}

/** Every event the gateway can push during a listen session. */
export type ListenEvent =
  | SessionOpenEvent
  | TranscriptEvent
  | SpeechStartedEvent
  | UtteranceEndEvent
  | ProviderSwitchedEvent
  | TextDeltaEvent
  | ClearedEvent
  | KeepAliveEvent
  | DoneEvent
  | ErrorEvent

/* ---- catalog + batch ------------------------------------------------- */

export interface ModelCapabilities {
  interim_results?: boolean
  word_timestamps?: boolean
  diarization?: boolean
  endpointing?: boolean
  keyword_boosting?: boolean
  languages?: string[]
  [key: string]: unknown
}

export interface Model {
  slug: string
  provider: string
  name?: string
  kind: string
  modes?: string[]
  pricing?: {
    per_audio_second_usd?: number
    per_audio_minute_usd?: number
    per_audio_hour_usd?: number
    per_session_hour_usd?: number
    minimum_usd?: number
    /** @deprecated derived by the gateway; prefer the native-unit fields */
    per_second_usd?: number
    [key: string]: unknown
  }
  capabilities?: ModelCapabilities
  hipaa_eligible?: boolean
  [key: string]: unknown
}

export interface Transcription {
  text: string
}

export interface VerboseTranscription {
  task: string
  language: string | null
  duration: number | null
  text: string
  words: Array<{ word: string; start: number; end: number; [key: string]: unknown }>
  model: string
  provider_raw?: Record<string, unknown>
  [key: string]: unknown
}
