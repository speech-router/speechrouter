import { SpeechRouterError } from './errors'
import type { ErrorCode, Model, Transcription, VerboseTranscription } from './events'

/** responseFormat → return type map for transcribe(). */
export type TranscribeFormats = {
  json: Transcription
  verbose_json: VerboseTranscription
  srt: string
  vtt: string
  text: string
}
import { buildListenUrl, ListenStream, type ListenOptions } from './listen'
import { buildSpeakUrl, SpeakStream, type SpeakOptions } from './speak'

export interface SpeechOptions {
  /** TTS model slug, e.g. "openai/gpt-4o-mini-tts". */
  model: string
  input: string
  voice?: string
  /** mp3 | opus | aac | flac | wav | pcm | mulaw | alaw (per model). */
  responseFormat?: string
  sampleRate?: number
  speed?: number
  instructions?: string
  language?: string
  providerParams?: Record<string, unknown>
  signal?: AbortSignal
}

export interface SpeechRouterOptions {
  /** Your sk_sr_... key. In browsers, prefer a short-lived key minted by
   * your backend — anything shipped to a page is public. */
  apiKey: string
  /** Override for self-hosted gateways, e.g. "http://localhost:8080". */
  baseUrl?: string
  /** Custom fetch (tests, polyfills). Defaults to globalThis.fetch. */
  fetch?: typeof fetch
  /** Extra headers on every REST request (tracing, proxies). */
  headers?: Record<string, string>
}

/** File input accepted by transcribe(): browser File/Blob, raw bytes, or a
 * React Native file descriptor ({ uri, name, type }). */
export type FileInput =
  | Blob
  | ArrayBuffer
  | Uint8Array
  | { uri: string; name: string; type: string }

export interface TranscribeOptions {
  model: string
  file?: FileInput
  /** Let the gateway fetch the audio itself instead of uploading. */
  url?: string
  /** Filename hint when passing raw bytes. Default "audio". */
  filename?: string
  language?: string
  diarization?: boolean
  keyterms?: string[]
  includeRaw?: boolean
  providerParams?: Record<string, unknown>
  /** Abort the request (e.g. AbortSignal.timeout(30_000)). */
  signal?: AbortSignal
}

const DEFAULT_BASE = 'https://api.speechrouter.ai'

export class SpeechRouter {
  private apiKey: string
  private base: string
  private wsBase: string
  private fetchImpl: typeof fetch
  private extraHeaders: Record<string, string>

  constructor(opts: SpeechRouterOptions) {
    if (!opts.apiKey) throw new SpeechRouterError('apiKey is required', { code: 'auth_failed' })
    this.apiKey = opts.apiKey
    this.base = (opts.baseUrl ?? DEFAULT_BASE).replace(/\/+$/, '')
    this.wsBase = this.base.replace(/^http/, 'ws')
    this.fetchImpl = opts.fetch ?? globalThis.fetch?.bind(globalThis)
    this.extraHeaders = opts.headers ?? {}
    if (!this.fetchImpl)
      throw new SpeechRouterError('no fetch available in this runtime', { code: 'internal_error' })
  }

  /** Open a live transcription session over WebSocket. */
  listen(opts: ListenOptions): ListenStream {
    return new ListenStream(buildListenUrl(this.wsBase, opts), opts, this.apiKey)
  }

  /** Open a streaming text-to-speech session over WebSocket. */
  speak(opts: SpeakOptions): SpeakStream {
    return new SpeakStream(buildSpeakUrl(this.wsBase, opts), this.apiKey)
  }

  /** Synthesize speech; resolves with the whole audio file. */
  async speech(opts: SpeechOptions): Promise<ArrayBuffer> {
    const response = await this.speechRequest(opts, false)
    return response.arrayBuffer()
  }

  /** Synthesize speech; the body streams as audio is generated. */
  async speechStream(opts: SpeechOptions): Promise<ReadableStream<Uint8Array>> {
    const response = await this.speechRequest(opts, true)
    if (!response.body)
      throw new SpeechRouterError('response has no body', { code: 'internal_error' })
    return response.body
  }

  private speechRequest(opts: SpeechOptions, stream: boolean): Promise<Response> {
    const body: Record<string, unknown> = { model: opts.model, input: opts.input, stream }
    if (opts.voice) body.voice = opts.voice
    if (opts.responseFormat) body.response_format = opts.responseFormat
    if (opts.sampleRate) body.sample_rate = opts.sampleRate
    if (opts.speed !== undefined) body.speed = opts.speed
    if (opts.instructions) body.instructions = opts.instructions
    if (opts.language) body.language = opts.language
    if (opts.providerParams) body.provider_params = opts.providerParams
    return this.request('/v1/audio/speech', {
      method: 'POST',
      body: JSON.stringify(body),
      headers: { 'Content-Type': 'application/json' },
      ...(opts.signal ? { signal: opts.signal } : {}),
    })
  }

  /** Transcribe a complete file. Return type follows `responseFormat`:
   * json → { text }, verbose_json → VerboseTranscription, srt/vtt/text → string. */
  async transcribe<F extends keyof TranscribeFormats = 'json'>(
    opts: TranscribeOptions & { responseFormat?: F },
  ): Promise<TranscribeFormats[F]> {
    const form = new FormData()
    form.set('model', opts.model)
    if (opts.responseFormat) form.set('response_format', opts.responseFormat)
    if (opts.language) form.set('language', opts.language)
    if (opts.diarization) form.set('diarization', 'true')
    if (opts.keyterms?.length) form.set('keyterms', opts.keyterms.join(','))
    if (opts.includeRaw) form.set('include_raw', 'true')
    if (opts.providerParams && Object.keys(opts.providerParams).length)
      form.set('provider_params', JSON.stringify(opts.providerParams))

    if (opts.url) {
      form.set('url', opts.url)
    } else if (opts.file !== undefined) {
      form.set('file', this.toFormPart(opts.file), this.partName(opts.file, opts.filename))
    } else {
      throw new SpeechRouterError('transcribe needs a file or a url', { code: 'invalid_request' })
    }

    const response = await this.request('/v1/audio/transcriptions', {
      method: 'POST',
      body: form,
      ...(opts.signal ? { signal: opts.signal } : {}),
    })
    const contentType = response.headers.get('content-type') ?? ''
    if (contentType.includes('application/json')) return response.json()
    return response.text() as Promise<TranscribeFormats[F]>
  }

  /**
   * Mint a short-lived token for client-side use (browsers, mobile).
   * Call this from YOUR BACKEND with your real key, hand the token to the
   * client, and construct its SpeechRouter with `apiKey: token`. TTL only
   * limits how long the token can open connections — an opened stream runs
   * to completion regardless.
   */
  async createToken(opts: { ttlSeconds?: number } = {}): Promise<{
    token: string
    expires_at: string
    ttl_seconds: number
  }> {
    const response = await this.request('/v1/tokens', {
      method: 'POST',
      body: JSON.stringify(opts.ttlSeconds ? { ttl_seconds: opts.ttlSeconds } : {}),
    })
    return response.json()
  }

  /** The live model catalog — slugs, capabilities, pricing. */
  async listModels(opts: { signal?: AbortSignal } = {}): Promise<Model[]> {
    const response = await this.request('/v1/models', {
      method: 'GET',
      ...(opts.signal ? { signal: opts.signal } : {}),
    })
    const payload = (await response.json()) as { data?: Model[] }
    return payload.data ?? []
  }

  /* ---- internals ----------------------------------------------------- */

  private toFormPart(file: FileInput): Blob {
    if (file instanceof Uint8Array)
      // Copy into a fresh ArrayBuffer so SharedArrayBuffer-backed views are boxed too.
      return new Blob([file.slice().buffer])
    if (file instanceof ArrayBuffer) return new Blob([file])
    // RN descriptor rides FormData natively; the cast keeps web types happy.
    return file as Blob
  }

  private partName(file: FileInput, filename?: string): string {
    if (filename) return filename
    if (typeof File !== 'undefined' && file instanceof File) return file.name
    return 'audio'
  }

  private async request(path: string, init: RequestInit): Promise<Response> {
    let response: Response
    try {
      response = await this.fetchImpl(`${this.base}${path}`, {
        ...init,
        headers: {
          ...this.extraHeaders,
          ...(init.headers as Record<string, string> | undefined),
          Authorization: `Bearer ${this.apiKey}`,
        },
      })
    } catch (err) {
      throw new SpeechRouterError(
        err instanceof Error ? err.message : 'network request failed',
        { code: 'connection_failed' },
      )
    }
    if (response.ok) return response

    let code: ErrorCode = 'internal_error'
    let message = `HTTP ${response.status}`
    let recoverable = response.status >= 500 || response.status === 429
    try {
      const body = (await response.json()) as {
        error?: { code?: ErrorCode; message?: string; recoverable?: boolean }
      }
      if (body.error?.code) code = body.error.code
      if (body.error?.message) message = body.error.message
      if (typeof body.error?.recoverable === 'boolean') recoverable = body.error.recoverable
    } catch {
      /* non-JSON error body; keep the status line */
    }
    throw new SpeechRouterError(message, { code, status: response.status, recoverable })
  }
}
