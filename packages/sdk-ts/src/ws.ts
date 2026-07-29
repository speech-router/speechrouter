/* Runtime-adaptive WebSocket: browsers and React Native have a global;
 * Node 22+ ships one (undici); older Node falls back to the optional `ws`
 * peer dependency. Everything downstream codes against the browser API. */

export interface WSLike {
  binaryType: string
  readonly readyState: number
  readonly bufferedAmount?: number
  send(data: string | ArrayBufferLike | ArrayBufferView): void
  close(code?: number, reason?: string): void
  addEventListener(type: string, listener: (event: any) => void): void
}

export type WSConstructor = new (url: string, protocols?: string | string[]) => WSLike

export async function resolveWebSocket(): Promise<WSConstructor> {
  const g = globalThis as Record<string, unknown>
  if (typeof g.WebSocket === 'function') return g.WebSocket as WSConstructor
  try {
    const mod = await import(/* webpackIgnore: true */ 'ws')
    return (mod.WebSocket ?? mod.default) as WSConstructor
  } catch {
    throw new Error(
      'No WebSocket implementation found. On Node 18-21 the ws package is required: npm install ws. Node >= 22 and browsers need nothing.',
    )
  }
}
