import { SpeechRouterError } from './errors'
import type {
  AudioChunkEvent,
  ClearedEvent,
  DoneEvent,
  ErrorEvent,
  SessionOpenEvent,
  SpeakEvent,
} from './events'
import { resolveWebSocket, type WSLike } from './ws'

export interface SpeakOptions {
  /** TTS model slug, e.g. "openai/gpt-4o-mini-tts". */
  model: string
  voice?: string
  /** Audio you receive. Default "linear16" (s16le mono at the model's rate). */
  encoding?: 'linear16' | 'mulaw' | 'alaw' | 'mp3' | 'opus' | (string & {})
  sampleRate?: number
  speed?: number
  language?: string
  instructions?: string
  providerParams?: Record<string, unknown>
}

export function buildSpeakUrl(wsBase: string, opts: SpeakOptions): string {
  const q = new URLSearchParams()
  q.set('model', opts.model)
  q.set('encoding', opts.encoding ?? 'linear16')
  if (opts.voice) q.set('voice', opts.voice)
  if (opts.sampleRate) q.set('sample_rate', String(opts.sampleRate))
  if (opts.speed !== undefined) q.set('speed', String(opts.speed))
  if (opts.language) q.set('language', opts.language)
  if (opts.instructions) q.set('instructions', opts.instructions)
  if (opts.providerParams && Object.keys(opts.providerParams).length)
    q.set('provider_params', JSON.stringify(opts.providerParams))
  return `${wsBase}/v1/speak?${q.toString()}`
}

/**
 * A streaming text-to-speech session (WSS /v1/speak). Send text as your LLM
 * produces it; iterate to receive audio in order.
 *
 *   const tts = sr.speak({ model: 'openai/gpt-4o-mini-tts', voice: 'marin' })
 *   for (const token of tokens) tts.sendText(token)
 *   tts.finalize()
 *   for await (const event of tts) if (event.type === 'audio') play(event.data)
 */
export class SpeakStream {
  private ws: WSLike | null = null
  private outbox: string[] = []
  private queue: SpeakEvent[] = []
  private waiter: ((r: IteratorResult<SpeakEvent>) => void) | null = null
  private pending: AudioChunkEvent | null = null
  private resolveDone!: (d: DoneEvent) => void
  private rejectDone!: (e: SpeechRouterError) => void
  private donePromise: Promise<DoneEvent>
  state: 'connecting' | 'open' | 'finalizing' | 'closed' = 'connecting'
  session: SessionOpenEvent | null = null

  constructor(
    private url: string,
    private apiKey: string,
  ) {
    this.donePromise = new Promise((resolve, reject) => {
      this.resolveDone = resolve
      this.rejectDone = reject
    })
    this.donePromise.catch(() => {})
    void this.connect()
  }

  private async connect(): Promise<void> {
    try {
      const WS = await resolveWebSocket()
      this.ws = new WS(this.url, ['bearer', this.apiKey])
    } catch (err) {
      this.finish(new SpeechRouterError(err instanceof Error ? err.message : 'could not open socket',
        { code: 'connection_failed' }))
      return
    }
    const ws = this.ws
    ws.binaryType = 'arraybuffer'
    ws.addEventListener('open', () => {
      if (this.state === 'closed') return
      if (this.state === 'connecting') this.state = 'open'
      for (const frame of this.outbox) ws.send(frame)
      this.outbox = []
    })
    ws.addEventListener('message', (e: { data: unknown }) => void this.onMessage(e.data))
    ws.addEventListener('close', () =>
      this.finish(new SpeechRouterError('connection closed before the session finished',
        { code: 'connection_closed' })))
  }

  private async onMessage(data: unknown): Promise<void> {
    if (typeof data !== 'string') {
      const buffer = data instanceof ArrayBuffer ? data
        : typeof (data as Blob)?.arrayBuffer === 'function' ? await (data as Blob).arrayBuffer()
          : null
      if (buffer && this.pending) {
        const chunk = this.pending
        this.push({ type: 'audio', seq: chunk.seq, data: buffer,
          ...(chunk.start !== undefined ? { start: chunk.start } : {}) })
        this.pending = null
      }
      return
    }
    let event: SpeakEvent | AudioChunkEvent
    try {
      event = JSON.parse(data)
    } catch {
      return
    }
    switch (event.type) {
      case 'audio.chunk':
        this.pending = event // its audio is the next binary frame
        return
      case 'session.open':
        this.session = event
        break
      case 'done':
        this.resolveDone(event)
        this.push(event)
        this.close()
        return
      case 'error': {
        const err = event as ErrorEvent
        this.rejectDone(new SpeechRouterError(err.message,
          { code: err.code, ...(err.provider ? { provider: err.provider } : {}) }))
        break
      }
    }
    this.push(event as SessionOpenEvent | ClearedEvent | ErrorEvent)
  }

  private send(payload: Record<string, unknown>): void {
    const frame = JSON.stringify(payload)
    if (this.state === 'closed')
      throw new SpeechRouterError('cannot send: stream is closed', { code: 'connection_closed' })
    if (this.ws && this.state !== 'connecting') this.ws.send(frame)
    else this.outbox.push(frame)
  }

  /** Append text to speak; fragments are fine, the gateway segments. */
  sendText(text: string): void {
    this.send({ type: 'text.delta', text })
  }

  /** Barge-in: drop queued and in-flight audio; a `cleared` event follows.
   * playbackMs: audio actually played so far, if known (used by providers that
   * report text_spoken, e.g. Deepgram Flux). */
  clear(playbackMs?: number): void {
    this.send(playbackMs === undefined ? { type: 'clear' } : { type: 'clear', playback_ms: playbackMs })
  }

  /** No more text: the rest is spoken, then `done`. */
  finalize(): void {
    this.send({ type: 'finalize' })
    if (this.state === 'open') this.state = 'finalizing'
  }

  /** Resolves with the usage summary when the session completes. */
  done(): Promise<DoneEvent> {
    return this.donePromise
  }

  close(): void {
    try {
      this.ws?.close()
    } catch {
      /* already closed */
    }
    this.finish(null)
  }

  private finish(err: SpeechRouterError | null): void {
    if (this.state === 'closed') return
    this.state = 'closed'
    if (err) this.rejectDone(err)
    if (this.waiter) {
      this.waiter({ value: undefined, done: true })
      this.waiter = null
    }
  }

  private push(event: SpeakEvent): void {
    if (this.waiter) {
      this.waiter({ value: event, done: false })
      this.waiter = null
    } else this.queue.push(event)
  }

  [Symbol.asyncIterator](): AsyncIterator<SpeakEvent> {
    return {
      next: () => {
        const queued = this.queue.shift()
        if (queued) return Promise.resolve({ value: queued, done: false })
        if (this.state === 'closed') return Promise.resolve({ value: undefined, done: true })
        return new Promise((resolve) => (this.waiter = resolve))
      },
      return: () => {
        this.close()
        return Promise.resolve({ value: undefined, done: true })
      },
    }
  }
}
