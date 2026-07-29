import { SpeechRouterError } from './errors'
import type {
  DoneEvent,
  ListenEvent,
  ProviderSwitchedEvent,
  SessionOpenEvent,
  TranscriptEvent,
} from './events'
import { resolveWebSocket, type WSLike } from './ws'

export interface ListenOptions {
  /** Model slug, e.g. "deepgram/nova-3". */
  model: string
  /** Ordered failover lane, e.g. ["soniox/stt-rt-v5"]. */
  fallbacks?: string[]
  /** PCM encoding of the audio you will send. Default "linear16". */
  encoding?: string
  /** Sample rate of the audio you will send. Default 16000. */
  sampleRate?: number
  /** Channel count. Default 1. */
  channels?: number
  language?: string
  /** Emit non-final hypotheses. Default true. */
  interimResults?: boolean
  diarization?: boolean
  /** Bias recognition toward these terms (when the model supports it). */
  keyterms?: string[]
  /** Attach the untouched provider payload to every transcript. */
  includeRaw?: boolean
  /** Escape hatch: raw params forwarded to the provider. */
  providerParams?: Record<string, unknown>
  /** Abort the dial if the socket is not open in this many ms. Default 10000. */
  connectTimeoutMs?: number
  /**
   * Keep the session alive through silences by sending keepalive frames.
   * true = every 8000 ms, a number = that interval, false = off (default
   * true). Note: an open session bills wall-clock time on session-billed
   * providers — close streams you are done with.
   */
  keepAlive?: boolean | number
}

type Listener<E> = (event: E) => void

export interface ListenEventMap {
  /** Socket is open and the gateway accepted the session. */
  open: SessionOpenEvent
  transcript: TranscriptEvent
  provider_switched: ProviderSwitchedEvent
  done: DoneEvent
  error: SpeechRouterError
  /** Fired exactly once, after every other event. */
  close: { code?: number; reason?: string }
  /** Every wire event, untouched — including ones without a named channel. */
  event: ListenEvent
}

const CLIENT_CODES = new Set([
  'connection_failed',
  'connection_closed',
  'timeout',
])

function toQuery(opts: ListenOptions, apiKey: string): string {
  const q = new URLSearchParams()
  q.set('model', opts.model)
  if (opts.fallbacks?.length) q.set('fallbacks', opts.fallbacks.join(','))
  q.set('encoding', opts.encoding ?? 'linear16')
  q.set('sample_rate', String(opts.sampleRate ?? 16000))
  q.set('channels', String(opts.channels ?? 1))
  if (opts.language) q.set('language', opts.language)
  if (opts.interimResults === false) q.set('interim_results', 'false')
  if (opts.diarization) q.set('diarization', 'true')
  if (opts.keyterms?.length) q.set('keyterms', opts.keyterms.join(','))
  if (opts.includeRaw) q.set('include_raw', 'true')
  if (opts.providerParams && Object.keys(opts.providerParams).length)
    q.set('provider_params', JSON.stringify(opts.providerParams))
  q.set('api_key', apiKey)
  return q.toString()
}

export function buildListenUrl(wsBase: string, opts: ListenOptions, apiKey: string): string {
  return `${wsBase}/v1/listen?${toQuery(opts, apiKey)}`
}

/**
 * A live transcription session. Create via `client.listen(...)`, then send
 * PCM with `sendAudio()` and consume events with `on()` or `for await`.
 */
export class ListenStream {
  private ws: WSLike | null = null
  private listeners = new Map<keyof ListenEventMap, Set<Listener<any>>>()
  private sendQueue: (ArrayBufferLike | ArrayBufferView)[] = []
  private iterQueue: ListenEvent[] = []
  private iterWaiter: ((r: IteratorResult<ListenEvent>) => void) | null = null
  private keepAliveTimer: ReturnType<typeof setInterval> | null = null
  private connectTimer: ReturnType<typeof setTimeout> | null = null
  private donePromise: Promise<DoneEvent>
  private resolveDone!: (d: DoneEvent) => void
  private rejectDone!: (e: SpeechRouterError) => void
  private doneSettled = false

  /** 'connecting' → 'open' → 'closed'; 'finalizing' between finalize() and done. */
  state: 'connecting' | 'open' | 'finalizing' | 'closed' = 'connecting'
  /** Set once the gateway confirms the session. */
  session: SessionOpenEvent | null = null

  constructor(private url: string, private opts: ListenOptions) {
    this.donePromise = new Promise((resolve, reject) => {
      this.resolveDone = resolve
      this.rejectDone = reject
    })
    // A caller may only await done(); don't let that surface as unhandled.
    this.donePromise.catch(() => {})
    void this.connect()
  }

  /* ---- event plumbing ------------------------------------------------ */

  on<K extends keyof ListenEventMap>(type: K, fn: Listener<ListenEventMap[K]>): () => void {
    let set = this.listeners.get(type)
    if (!set) this.listeners.set(type, (set = new Set()))
    set.add(fn)
    return () => set!.delete(fn)
  }

  once<K extends keyof ListenEventMap>(type: K, fn: Listener<ListenEventMap[K]>): () => void {
    const off = this.on(type, (e) => {
      off()
      fn(e)
    })
    return off
  }

  private emit<K extends keyof ListenEventMap>(type: K, event: ListenEventMap[K]): void {
    this.listeners.get(type)?.forEach((fn) => fn(event))
  }

  /** Consume the session as an async stream of wire events. */
  [Symbol.asyncIterator](): AsyncIterator<ListenEvent> {
    return {
      next: (): Promise<IteratorResult<ListenEvent>> => {
        const queued = this.iterQueue.shift()
        if (queued) return Promise.resolve({ value: queued, done: false })
        if (this.state === 'closed') return Promise.resolve({ value: undefined, done: true })
        return new Promise((resolve) => (this.iterWaiter = resolve))
      },
      return: (): Promise<IteratorResult<ListenEvent>> => {
        this.close()
        return Promise.resolve({ value: undefined, done: true })
      },
    }
  }

  /* ---- lifecycle ----------------------------------------------------- */

  private async connect(): Promise<void> {
    let WS
    try {
      WS = await resolveWebSocket()
      this.ws = new WS(this.url)
    } catch (err) {
      this.fail(
        new SpeechRouterError(err instanceof Error ? err.message : 'could not open socket', {
          code: 'connection_failed',
        }),
      )
      return
    }
    const ws = this.ws
    ws.binaryType = 'arraybuffer'

    const timeoutMs = this.opts.connectTimeoutMs ?? 10_000
    this.connectTimer = setTimeout(() => {
      if (this.state === 'connecting') {
        this.fail(new SpeechRouterError(`socket not open after ${timeoutMs}ms`, { code: 'timeout' }))
        try {
          ws.close()
        } catch {
          /* already dead */
        }
      }
    }, timeoutMs)

    ws.addEventListener('open', () => {
      if (this.connectTimer) clearTimeout(this.connectTimer)
      if (this.state !== 'connecting') return
      this.state = 'open'
      for (const chunk of this.sendQueue) ws.send(chunk)
      this.sendQueue = []
      this.startKeepAlive()
    })

    ws.addEventListener('message', (e: { data: unknown }) => {
      void this.handleMessage(e.data)
    })

    ws.addEventListener('error', () => {
      // The close event carries the useful signal; error objects here are
      // implementation-specific noise. Connection-phase failures reject fast:
      if (this.state === 'connecting') {
        this.fail(new SpeechRouterError('websocket connection failed', { code: 'connection_failed' }))
      }
    })

    ws.addEventListener('close', (e: { code?: number; reason?: string }) => {
      this.teardown(e.code, e.reason)
    })
  }

  private async handleMessage(data: unknown): Promise<void> {
    let text: string
    if (typeof data === 'string') text = data
    else if (data instanceof ArrayBuffer) text = new TextDecoder().decode(data)
    else if (typeof (data as Blob)?.text === 'function') text = await (data as Blob).text()
    else return
    let event: ListenEvent
    try {
      event = JSON.parse(text) as ListenEvent
    } catch {
      return
    }

    this.emit('event', event)
    this.pushIter(event)

    switch (event.type) {
      case 'session.open':
        this.session = event
        this.emit('open', event)
        break
      case 'transcript':
        this.emit('transcript', event)
        break
      case 'provider_switched':
        this.emit('provider_switched', event)
        break
      case 'done':
        this.settleDone(event)
        this.emit('done', event)
        break
      case 'error': {
        const err = new SpeechRouterError(event.message, {
          code: event.code,
          recoverable: event.recoverable ?? false,
          ...(event.provider !== undefined ? { provider: event.provider } : {}),
        })
        if (!event.recoverable) this.settleDoneWith(err)
        this.emit('error', err)
        break
      }
    }
  }

  private pushIter(event: ListenEvent): void {
    if (this.iterWaiter) {
      const w = this.iterWaiter
      this.iterWaiter = null
      w({ value: event, done: false })
    } else {
      this.iterQueue.push(event)
    }
  }

  private startKeepAlive(): void {
    const setting = this.opts.keepAlive ?? true
    if (setting === false) return
    const interval = typeof setting === 'number' ? setting : 8000
    this.keepAliveTimer = setInterval(() => {
      if (this.state === 'open') this.sendJson({ type: 'keepalive' })
    }, interval)
  }

  private fail(err: SpeechRouterError): void {
    this.settleDoneWith(err)
    this.emit('error', err)
    this.teardown()
  }

  private settleDone(d: DoneEvent): void {
    if (!this.doneSettled) {
      this.doneSettled = true
      this.resolveDone(d)
    }
  }

  private settleDoneWith(err: SpeechRouterError): void {
    if (!this.doneSettled) {
      this.doneSettled = true
      this.rejectDone(err)
    }
  }

  private teardown(code?: number, reason?: string): void {
    if (this.state === 'closed') return
    this.state = 'closed'
    if (this.keepAliveTimer) clearInterval(this.keepAliveTimer)
    if (this.connectTimer) clearTimeout(this.connectTimer)
    this.settleDoneWith(
      new SpeechRouterError('connection closed before the session finished', {
        code: 'connection_closed',
      }),
    )
    if (this.iterWaiter) {
      const w = this.iterWaiter
      this.iterWaiter = null
      w({ value: undefined, done: true })
    }
    this.emit('close', {
      ...(code !== undefined ? { code } : {}),
      ...(reason !== undefined ? { reason } : {}),
    })
  }

  /* ---- outbound ------------------------------------------------------ */

  /** Send a chunk of PCM audio. Chunks sent before the socket opens are queued. */
  sendAudio(chunk: ArrayBufferLike | ArrayBufferView): void {
    if (this.state === 'closed' || this.state === 'finalizing')
      throw new SpeechRouterError('cannot send audio: stream is ' + this.state, {
        code: 'connection_closed',
      })
    if (this.state === 'connecting') {
      this.sendQueue.push(chunk)
      return
    }
    this.ws!.send(chunk)
  }

  /** Bytes accepted but not yet on the wire — use to pace large sends. */
  get bufferedAmount(): number {
    return this.ws?.bufferedAmount ?? 0
  }

  private sendJson(msg: Record<string, unknown>): void {
    if (this.state === 'open' || this.state === 'finalizing') this.ws!.send(JSON.stringify(msg))
  }

  /** Ask the gateway to flush pending audio into a final transcript. */
  finalize(): void {
    if (this.state === 'open') {
      this.state = 'finalizing'
      this.sendJson({ type: 'finalize' })
    }
  }

  /** Resolves with the gateway's usage summary once the session completes. */
  done(): Promise<DoneEvent> {
    return this.donePromise
  }

  /**
   * Graceful shutdown: finalize, wait for the `done` usage event, close the
   * socket. Returns the done event; rejects if the session errored.
   */
  async stop(timeoutMs = 30_000): Promise<DoneEvent> {
    this.finalize()
    const timeout = new Promise<never>((_, reject) =>
      setTimeout(
        () => reject(new SpeechRouterError('gave up waiting for done', { code: 'timeout' })),
        timeoutMs,
      ),
    )
    try {
      return await Promise.race([this.donePromise, timeout])
    } finally {
      this.close()
    }
  }

  /** Immediate shutdown. In-flight audio may go untranscribed — prefer stop(). */
  close(): void {
    try {
      this.ws?.close(1000)
    } catch {
      /* already closed */
    }
    this.teardown()
  }
}

export function isClientCode(code: string): boolean {
  return CLIENT_CODES.has(code)
}
