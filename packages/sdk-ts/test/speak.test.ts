import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { WebSocketServer } from 'ws'
import { SpeechRouter } from '../src/client'
import type { SpeakEvent } from '../src/events'
import { SpeechRouterError } from '../src/errors'

let server: WebSocketServer
let port: number
let lastUrl: string | undefined
let received: string[]

beforeEach(async () => {
  received = []
  server = new WebSocketServer({ port: 0, handleProtocols: () => 'bearer' })
  await new Promise<void>((resolve) => server.once('listening', resolve))
  port = (server.address() as { port: number }).port
  server.on('connection', (socket, request) => {
    lastUrl = request.url
    socket.send(JSON.stringify({ type: 'session.open', session_id: 'speak_1',
      model: 'openai/gpt-4o-mini-tts', voice: 'marin' }))
    socket.on('message', (data) => {
      const event = JSON.parse(data.toString())
      received.push(event.type)
      if (event.type === 'finalize') {
        for (const seq of [1, 2]) {
          socket.send(JSON.stringify({ type: 'audio.chunk', seq, start: 0 }))
          socket.send(Buffer.from([seq, seq]))
        }
        socket.send(JSON.stringify({ type: 'done', usage: { characters: 5 } }))
      }
    })
  })
})

afterEach(async () => {
  for (const socket of server.clients) socket.terminate()
  await new Promise<void>((resolve) => server.close(() => resolve()))
})

describe('speak', () => {
  it('queues text until open, pairs chunk metadata with audio, resolves done', async () => {
    const sr = new SpeechRouter({ apiKey: 'sk_sr_test', baseUrl: `http://127.0.0.1:${port}` })
    const tts = sr.speak({ model: 'openai/gpt-4o-mini-tts', voice: 'marin' })
    tts.sendText('Hello')
    tts.finalize()
    const events: SpeakEvent[] = []
    for await (const event of tts) events.push(event)
    expect(received).toEqual(['text.delta', 'finalize'])
    const audio = events.filter((e) => e.type === 'audio')
    expect(audio.map((e) => [e.seq, [...new Uint8Array(e.data)]])).toEqual([[1, [1, 1]], [2, [2, 2]]])
    expect(tts.session?.voice).toBe('marin')
    expect((await tts.done()).usage.characters).toBe(5)
    const q = new URLSearchParams(lastUrl!.split('?')[1])
    expect(q.get('model')).toBe('openai/gpt-4o-mini-tts')
    expect(q.get('encoding')).toBe('linear16')
  })
})

describe('speech', () => {
  it('posts JSON and returns audio bytes; errors map to SpeechRouterError', async () => {
    const calls: RequestInit[] = []
    const impl = (async (_url: string, init: RequestInit) => {
      calls.push(init)
      const body = JSON.parse(init.body as string)
      if (body.model === 'nope/x')
        return new Response(JSON.stringify({ error: { code: 'model_not_found', message: 'no' } }),
          { status: 404, headers: { 'content-type': 'application/json' } })
      return new Response(new Uint8Array([9, 9, 9]), { status: 200 })
    }) as unknown as typeof fetch
    const sr = new SpeechRouter({ apiKey: 'k', baseUrl: 'https://gw.test', fetch: impl })
    const audio = await sr.speech({ model: 'openai/tts-1', input: 'hi', voice: 'alloy', speed: 1.5 })
    expect([...new Uint8Array(audio)]).toEqual([9, 9, 9])
    expect(JSON.parse(calls[0]!.body as string)).toEqual({
      model: 'openai/tts-1', input: 'hi', stream: false, voice: 'alloy', speed: 1.5 })
    const stream = await sr.speechStream({ model: 'openai/tts-1', input: 'hi' })
    expect(stream).toBeInstanceOf(ReadableStream)
    await expect(sr.speech({ model: 'nope/x', input: 'hi' })).rejects.toBeInstanceOf(SpeechRouterError)
  })
})
