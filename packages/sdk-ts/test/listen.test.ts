import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { WebSocketServer, type WebSocket as ServerSocket } from 'ws'
import { SpeechRouter } from '../src/client'
import type { ListenEvent, TranscriptEvent } from '../src/events'
import { SpeechRouterError } from '../src/errors'

let server: WebSocketServer
let port: number
let lastUrl: string | undefined
let lastSocket: ServerSocket | undefined
let received: (Buffer | string)[]

function client() {
  return new SpeechRouter({ apiKey: 'sk_sr_test', baseUrl: `http://127.0.0.1:${port}` })
}

const sessionOpen = JSON.stringify({
  type: 'session.open',
  session_id: 'sess_1',
  model: 'deepgram/nova-3',
})

beforeEach(async () => {
  received = []
  server = new WebSocketServer({ port: 0 })
  await new Promise<void>((resolve) => server.once('listening', resolve))
  port = (server.address() as { port: number }).port
  server.on('connection', (socket, request) => {
    lastUrl = request.url
    lastSocket = socket
    socket.on('message', (data, isBinary) => {
      received.push(isBinary ? (data as Buffer) : data.toString())
    })
  })
})

afterEach(async () => {
  // ws' close() waits for clients; streams left open by a test would hang it.
  for (const socket of server.clients) socket.terminate()
  await new Promise<void>((resolve) => server.close(() => resolve()))
})

describe('listen url', () => {
  it('carries the full option surface as query params', async () => {
    const stream = client().listen({
      model: 'deepgram/nova-3',
      fallbacks: ['soniox/stt-rt-v5', 'cartesia/ink-2'],
      language: 'en',
      interimResults: false,
      diarization: true,
      keyterms: ['metoprolol', 'SpeechRouter'],
      includeRaw: true,
      providerParams: { smart_format: false },
      keepAlive: false,
    })
    await new Promise<void>((resolve) => stream.on('close', () => resolve()) && setTimeout(() => stream.close(), 50))
    const q = new URLSearchParams(lastUrl!.split('?')[1])
    expect(q.get('model')).toBe('deepgram/nova-3')
    expect(q.get('fallbacks')).toBe('soniox/stt-rt-v5,cartesia/ink-2')
    expect(q.get('sample_rate')).toBe('16000')
    expect(q.get('interim_results')).toBe('false')
    expect(q.get('diarization')).toBe('true')
    expect(q.get('keyterms')).toBe('metoprolol,SpeechRouter')
    expect(q.get('include_raw')).toBe('true')
    expect(JSON.parse(q.get('provider_params')!)).toEqual({ smart_format: false })
    expect(q.get('api_key')).toBe('sk_sr_test')
  })
})

describe('session lifecycle', () => {
  it('queues audio sent before open, emits typed events, settles done()', async () => {
    const stream = client().listen({ model: 'deepgram/nova-3', keepAlive: false })
    stream.sendAudio(new Int16Array([1, 2, 3]).buffer) // before open -> queued

    const transcripts: TranscriptEvent[] = []
    stream.on('transcript', (t) => transcripts.push(t))
    const opened = new Promise<void>((resolve) => stream.on('open', () => resolve()))

    await new Promise<void>((resolve) => {
      const iv = setInterval(() => lastSocket && (clearInterval(iv), resolve()), 5)
    })
    lastSocket!.send(sessionOpen)
    lastSocket!.send(JSON.stringify({ type: 'transcript', is_final: false, text: 'never' }))
    lastSocket!.send(
      JSON.stringify({ type: 'transcript', is_final: true, text: 'never lose a word', end: 1.2 }),
    )
    lastSocket!.send(JSON.stringify({ type: 'done', usage: { audio_seconds: 1.2 } }))

    await opened
    const done = await stream.done()
    expect(done.usage.audio_seconds).toBe(1.2)
    expect(transcripts.map((t) => t.is_final)).toEqual([false, true])
    expect(stream.session?.session_id).toBe('sess_1')

    // the queued pre-open audio actually reached the server
    await new Promise((r) => setTimeout(r, 30))
    expect(received.some((m) => typeof m !== 'string' && m.length === 6)).toBe(true)
  })

  it('stop() finalizes, waits for done, then closes', async () => {
    const stream = client().listen({ model: 'deepgram/nova-3', keepAlive: false })
    await new Promise<void>((resolve) => {
      const iv = setInterval(() => lastSocket && (clearInterval(iv), resolve()), 5)
    })
    lastSocket!.send(sessionOpen)
    lastSocket!.on('message', (data, isBinary) => {
      if (!isBinary && JSON.parse(data.toString()).type === 'finalize') {
        lastSocket!.send(JSON.stringify({ type: 'transcript', is_final: true, text: 'tail' }))
        lastSocket!.send(JSON.stringify({ type: 'done', usage: { audio_seconds: 2 } }))
      }
    })
    const done = await stream.stop()
    expect(done.usage.audio_seconds).toBe(2)
    expect(stream.state).toBe('closed')
    expect(() => stream.sendAudio(new Uint8Array(2))).toThrow(SpeechRouterError)
  })

  it('maps gateway error events onto SpeechRouterError and rejects done()', async () => {
    const stream = client().listen({ model: 'deepgram/nova-3', keepAlive: false })
    const errors: SpeechRouterError[] = []
    stream.on('error', (e) => errors.push(e))
    await new Promise<void>((resolve) => {
      const iv = setInterval(() => lastSocket && (clearInterval(iv), resolve()), 5)
    })
    lastSocket!.send(
      JSON.stringify({
        type: 'error',
        code: 'concurrency_exceeded',
        message: 'limit reached',
        recoverable: false,
      }),
    )
    await expect(stream.done()).rejects.toMatchObject({ code: 'concurrency_exceeded' })
    expect(errors[0]).toBeInstanceOf(SpeechRouterError)
    expect(errors[0]!.message).toBe('limit reached')
  })

  it('supports for-await iteration and ends on close', async () => {
    const stream = client().listen({ model: 'deepgram/nova-3', keepAlive: false })
    await new Promise<void>((resolve) => {
      const iv = setInterval(() => lastSocket && (clearInterval(iv), resolve()), 5)
    })
    lastSocket!.send(sessionOpen)
    lastSocket!.send(JSON.stringify({ type: 'transcript', is_final: true, text: 'hi' }))
    lastSocket!.send(JSON.stringify({ type: 'done', usage: {} }))
    setTimeout(() => lastSocket!.close(1000), 40)

    const seen: string[] = []
    for await (const event of stream as AsyncIterable<ListenEvent>) {
      seen.push(event.type)
    }
    expect(seen).toEqual(['session.open', 'transcript', 'done'])
  })

  it('rejects with connection_failed when nothing is listening', async () => {
    const dead = new SpeechRouter({ apiKey: 'sk_sr_test', baseUrl: 'http://127.0.0.1:1' })
    const stream = dead.listen({ model: 'deepgram/nova-3', keepAlive: false })
    await expect(stream.done()).rejects.toMatchObject({ code: 'connection_failed' })
    expect(stream.state).toBe('closed')
  })

  it('sends keepalive frames on the configured interval', async () => {
    client().listen({ model: 'deepgram/nova-3', keepAlive: 30 })
    await new Promise<void>((resolve) => {
      const iv = setInterval(() => lastSocket && (clearInterval(iv), resolve()), 5)
    })
    await new Promise((r) => setTimeout(r, 110))
    const keepalives = received.filter(
      (m) => typeof m === 'string' && JSON.parse(m).type === 'keepalive',
    )
    expect(keepalives.length).toBeGreaterThanOrEqual(2)
  })
})
