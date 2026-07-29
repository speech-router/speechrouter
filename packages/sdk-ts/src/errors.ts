import type { ErrorCode } from './events'

/** Every failure the SDK surfaces is one of these. */
export class SpeechRouterError extends Error {
  /** Machine-readable code from the gateway's 16-code error enum, or a
   * client-side code ('connection_failed', 'connection_closed', 'timeout'). */
  readonly code: ErrorCode | 'connection_failed' | 'connection_closed' | 'timeout'
  /** HTTP status for REST calls; undefined for WebSocket errors. */
  readonly status?: number
  /** Which upstream provider tripped, when the gateway says. */
  readonly provider?: string
  /** Gateway's hint that retrying the same request may succeed. */
  readonly recoverable: boolean

  constructor(
    message: string,
    opts: {
      code: SpeechRouterError['code']
      status?: number
      provider?: string
      recoverable?: boolean
    },
  ) {
    super(message)
    this.name = 'SpeechRouterError'
    this.code = opts.code
    if (opts.status !== undefined) this.status = opts.status
    if (opts.provider !== undefined) this.provider = opts.provider
    this.recoverable = opts.recoverable ?? false
  }
}
