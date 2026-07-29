export { SpeechRouter } from './client'
export type { SpeechRouterOptions, TranscribeOptions, TranscribeFormats, FileInput } from './client'
export { ListenStream, buildListenUrl } from './listen'
export type { ListenOptions, ListenEventMap } from './listen'
export { SpeechRouterError } from './errors'
export type {
  ModelCapabilities,
  ListenEvent,
  SessionOpenEvent,
  TranscriptEvent,
  SpeechStartedEvent,
  UtteranceEndEvent,
  ProviderSwitchedEvent,
  TextDeltaEvent,
  ClearedEvent,
  KeepAliveEvent,
  DoneEvent,
  ErrorEvent,
  ErrorCode,
  Word,
  Model,
  Transcription,
  VerboseTranscription,
} from './events'
