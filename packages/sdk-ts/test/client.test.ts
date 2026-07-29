import { describe, expect, it } from 'vitest'
import { SpeechRouter } from '../src/client'
import { SpeechRouterError } from '../src/errors'

function fetchStub(handler: (url: string, init: RequestInit) => Response) {
  const calls: { url: string; init: RequestInit }[] = []
  const impl = (async (url: string, init: RequestInit) => {
    calls.push({ url, init })
    return handler(url, init)
  }) as unknown as typeof fetch
  return { impl, calls }
}

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })

describe('transcribe', () => {
  it('posts multipart with model, options, and file bytes', async () => {
    const { impl, calls } = fetchStub(() => json({ text: 'hello' }))
    const sr = new SpeechRouter({ apiKey: 'sk_sr_x', baseUrl: 'https://gw.test', fetch: impl })
    const result = await sr.transcribe({
      model: 'deepgram/nova-3',
      file: new Uint8Array([1, 2, 3, 4]),
      filename: 'clip.wav',
      diarization: true,
      keyterms: ['alpha'],
    })
    expect(result.text).toBe('hello')
    expect(calls[0]!.url).toBe('https://gw.test/v1/audio/transcriptions')
    expect((calls[0]!.init.headers as Record<string, string>).Authorization).toBe('Bearer sk_sr_x')
    const form = calls[0]!.init.body as FormData
    expect(form.get('model')).toBe('deepgram/nova-3')
    expect(form.get('diarization')).toBe('true')
    expect(form.get('keyterms')).toBe('alpha')
    const file = form.get('file') as File
    expect(file.name).toBe('clip.wav')
    expect(file.size).toBe(4)
  })

  it('returns raw text for srt/vtt/text formats', async () => {
    const { impl } = fetchStub(
      () => new Response('1\n00:00:00,000 --> 00:00:01,000\nhi\n', { status: 200 }),
    )
    const sr = new SpeechRouter({ apiKey: 'k', baseUrl: 'https://gw.test', fetch: impl })
    const srt = await sr.transcribe({
      model: 'deepgram/nova-3',
      url: 'https://example.com/a.wav',
      responseFormat: 'srt',
    })
    expect(srt).toContain('-->')
  })

  it('maps the error envelope to SpeechRouterError with code and status', async () => {
    const { impl } = fetchStub(() =>
      json({ error: { code: 'model_not_found', message: "unknown model 'nope/x'" } }, 404),
    )
    const sr = new SpeechRouter({ apiKey: 'k', baseUrl: 'https://gw.test', fetch: impl })
    await expect(
      sr.transcribe({ model: 'nope/x', file: new Uint8Array(1) }),
    ).rejects.toMatchObject({ code: 'model_not_found', status: 404 })
  })

  it('requires a file or url', async () => {
    const { impl } = fetchStub(() => json({}))
    const sr = new SpeechRouter({ apiKey: 'k', fetch: impl })
    await expect(sr.transcribe({ model: 'deepgram/nova-3' })).rejects.toBeInstanceOf(
      SpeechRouterError,
    )
  })
})

describe('listModels', () => {
  it('unwraps the data array', async () => {
    const { impl } = fetchStub(() => json({ data: [{ slug: 'deepgram/nova-3', provider: 'deepgram', kind: 'stt' }] }))
    const sr = new SpeechRouter({ apiKey: 'k', baseUrl: 'https://gw.test', fetch: impl })
    const models = await sr.listModels()
    expect(models).toHaveLength(1)
    expect(models[0]!.slug).toBe('deepgram/nova-3')
  })
})

describe('constructor', () => {
  it('refuses a missing api key', () => {
    expect(() => new SpeechRouter({ apiKey: '' })).toThrow(SpeechRouterError)
  })
})

describe('createToken', () => {
  it('posts ttl and returns the token payload', async () => {
    const { impl, calls } = fetchStub(() =>
      json({ token: 'st_abc', expires_at: '2026-01-01T00:00:00Z', ttl_seconds: 120 }),
    )
    const sr = new SpeechRouter({ apiKey: 'sk_sr_x', baseUrl: 'https://gw.test', fetch: impl })
    const out = await sr.createToken({ ttlSeconds: 120 })
    expect(out.token).toBe('st_abc')
    expect(calls[0]!.url).toBe('https://gw.test/v1/tokens')
    expect(JSON.parse(calls[0]!.init.body as string)).toEqual({ ttl_seconds: 120 })
  })
})
