import { SpeechRouterError } from './errors'
import type { ErrorCode, Model, Transcription, VerboseTranscription } from './events'
import { buildListenUrl, ListenStream, type ListenOptions } from './listen'

export interface SpeechRouterOptions {
  /** Your sk_sr_... key. In browsers, prefer a short-lived key minted by
   * your backend — anything shipped to a page is public. */
  apiKey: string
  /** Override for self-hosted gateways, e.g. "http://localhost:8080". */
  baseUrl?: string
  /** Custom fetch (tests, polyfills). Defaults to globalThis.fetch. */
  fetch?: typeof fetch
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
}

const DEFAULT_BASE = 'https://api.speechrouter.ai'

export class SpeechRouter {
  private apiKey: string
  private base: string
  private wsBase: string
  private fetchImpl: typeof fetch

  constructor(opts: SpeechRouterOptions) {
    if (!opts.apiKey) throw new SpeechRouterError('apiKey is required', { code: 'auth_failed' })
    this.apiKey = opts.apiKey
    this.base = (opts.baseUrl ?? DEFAULT_BASE).replace(/\/+$/, '')
    this.wsBase = this.base.replace(/^http/, 'ws')
    this.fetchImpl = opts.fetch ?? globalThis.fetch?.bind(globalThis)
    if (!this.fetchImpl)
      throw new SpeechRouterError('no fetch available in this runtime', { code: 'internal_error' })
  }

  /** Open a live transcription session over WebSocket. */
  listen(opts: ListenOptions): ListenStream {
    return new ListenStream(buildListenUrl(this.wsBase, opts, this.apiKey), opts)
  }

  /** Transcribe a complete file. Returns `{ text }`. */
  async transcribe(opts: TranscribeOptions): Promise<Transcription>
  async transcribe(
    opts: TranscribeOptions & { responseFormat: 'verbose_json' },
  ): Promise<VerboseTranscription>
  async transcribe(
    opts: TranscribeOptions & { responseFormat: 'srt' | 'vtt' | 'text' },
  ): Promise<string>
  async transcribe(
    opts: TranscribeOptions & { responseFormat?: string },
  ): Promise<Transcription | VerboseTranscription | string> {
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
    })
    const contentType = response.headers.get('content-type') ?? ''
    if (contentType.includes('application/json')) return response.json()
    return response.text()
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
  async listModels(): Promise<Model[]> {
    const response = await this.request('/v1/models', { method: 'GET' })
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
        headers: { Authorization: `Bearer ${this.apiKey}` },
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
    try {
      const body = (await response.json()) as {
        error?: { code?: ErrorCode; message?: string }
      }
      if (body.error?.code) code = body.error.code
      if (body.error?.message) message = body.error.message
    } catch {
      /* non-JSON error body; keep the status line */
    }
    throw new SpeechRouterError(message, {
      code,
      status: response.status,
      recoverable: response.status >= 500,
    })
  }
}
