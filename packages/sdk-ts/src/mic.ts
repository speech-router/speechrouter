/* Browser microphone capture → 16 kHz mono PCM, ready for ListenStream.
 *
 * Separate entry point ("speechrouter/mic") because it touches
 * getUserMedia/AudioContext — browser-only APIs that React Native and Node
 * bundles must never import. In React Native, capture PCM with a native
 * module (e.g. react-native-live-audio-stream) and feed stream.sendAudio().
 */

import type { ListenStream } from './listen'

export interface MicrophoneOptions {
  /** Target sample rate sent to the gateway. Default 16000. */
  sampleRate?: number
  echoCancellation?: boolean
  noiseSuppression?: boolean
  /** Called with the RMS level (0..1) of each captured block — drive a meter. */
  onLevel?: (rms: number) => void
}

export interface Microphone {
  /** The rate audio is actually captured at before resampling. */
  readonly captureSampleRate: number
  stop(): void
}

/**
 * Capture the default microphone and pump it into a listen stream.
 * Browsers ignore requested rates (a 96 kHz interface stays 96 kHz), so
 * audio is linearly resampled with cross-buffer phase continuity.
 */
export async function openMicrophone(
  stream: ListenStream,
  opts: MicrophoneOptions = {},
): Promise<Microphone> {
  const target = opts.sampleRate ?? 16000
  const media = await navigator.mediaDevices.getUserMedia({
    audio: {
      echoCancellation: opts.echoCancellation ?? true,
      noiseSuppression: opts.noiseSuppression ?? true,
      channelCount: 1,
    },
  })
  const ctx = new AudioContext()
  const source = ctx.createMediaStreamSource(media)
  const processor = ctx.createScriptProcessor(4096, 1, 1)
  const ratio = ctx.sampleRate / target
  let phase = 0

  processor.onaudioprocess = (e) => {
    const input = e.inputBuffer.getChannelData(0)
    if (opts.onLevel) {
      let sum = 0
      for (let i = 0; i < input.length; i++) sum += input[i]! * input[i]!
      opts.onLevel(Math.sqrt(sum / input.length))
    }
    const frames: number[] = []
    while (phase < input.length - 1) {
      const i = Math.floor(phase)
      const frac = phase - i
      frames.push(input[i]! * (1 - frac) + input[i + 1]! * frac)
      phase += ratio
    }
    phase -= input.length
    const pcm = new Int16Array(frames.length)
    for (let i = 0; i < frames.length; i++) {
      const s = Math.max(-1, Math.min(1, frames[i]!))
      pcm[i] = s < 0 ? s * 0x8000 : s * 0x7fff
    }
    if (stream.state === 'open' || stream.state === 'connecting') stream.sendAudio(pcm.buffer)
  }

  source.connect(processor)
  processor.connect(ctx.destination)

  return {
    captureSampleRate: ctx.sampleRate,
    stop() {
      processor.disconnect()
      source.disconnect()
      media.getTracks().forEach((t) => t.stop())
      void ctx.close()
    },
  }
}
