export { SpeechRouter } from './client'
export type {
  SpeechRouterOptions,
  TranscribeOptions,
  TranscribeFormats,
  FileInput,
  SpeechOptions,
} from './client'
export { ListenStream, buildListenUrl } from './listen'
export type { ListenOptions, ListenEventMap } from './listen'
export { SpeakStream, buildSpeakUrl } from './speak'
export type { SpeakOptions } from './speak'
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
  AudioChunkEvent,
  SpeakAudio,
  SpeakEvent,
  KeepAliveEvent,
  DoneEvent,
  ErrorEvent,
  ErrorCode,
  Word,
  Model,
  Transcription,
  VerboseTranscription,
} from './events'
export type { ProviderParamsMap } from './providerParams'
export type * from './providerParams'
