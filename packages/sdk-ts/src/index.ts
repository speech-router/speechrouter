export { SpeechRouter } from './client'
export type { SpeechRouterOptions, TranscribeOptions, FileInput } from './client'
export { ListenStream, buildListenUrl } from './listen'
export type { ListenOptions, ListenEventMap } from './listen'
export { SpeechRouterError } from './errors'
export type {
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
