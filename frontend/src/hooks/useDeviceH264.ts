import { useCallback, useEffect, useRef, useState } from 'react'
import type { RefObject } from 'react'
import { getWebSocketH264Url } from '../api/client'

const MSG_CONFIG = 0x01
const MSG_FRAME = 0x02

const MAX_BACKOFF_MS = 30_000
const BASE_DELAY_MS = 1_000

export type H264StreamStatus = 'idle' | 'connecting' | 'connected' | 'error'

function stripStartCode(nal: Uint8Array): Uint8Array {
  if (nal.length >= 4 && nal[0] === 0 && nal[1] === 0 && nal[3] === 1) {
    return nal.subarray(4)
  }
  if (nal.length >= 3 && nal[0] === 0 && nal[1] === 0 && nal[2] === 1) {
    return nal.subarray(3)
  }
  return nal
}

function splitAnnexB(data: Uint8Array): Uint8Array[] {
  const starts: number[] = []
  let i = 0
  while (i < data.length) {
    if (
      i + 3 <= data.length &&
      data[i] === 0 &&
      data[i + 1] === 0 &&
      data[i + 2] === 1
    ) {
      starts.push(i)
      i += 3
      continue
    }
    if (
      i + 4 <= data.length &&
      data[i] === 0 &&
      data[i + 1] === 0 &&
      data[i + 2] === 0 &&
      data[i + 3] === 1
    ) {
      starts.push(i)
      i += 4
      continue
    }
    i++
  }
  const out: Uint8Array[] = []
  for (let s = 0; s < starts.length; s++) {
    const from = starts[s]
    const to = s + 1 < starts.length ? starts[s + 1] : data.length
    if (to > from) out.push(data.subarray(from, to))
  }
  return out
}

function findSpsPps(configBlob: Uint8Array): { sps: Uint8Array; pps: Uint8Array } | null {
  const units = splitAnnexB(configBlob)
  let sps: Uint8Array | null = null
  let pps: Uint8Array | null = null
  for (const u of units) {
    let sc = 0
    if (u.length >= 4 && u[0] === 0 && u[1] === 0 && u[3] === 1) sc = 4
    else if (u.length >= 3 && u[0] === 0 && u[1] === 0 && u[2] === 1) sc = 3
    if (sc === 0 || u.length <= sc) continue
    const t = u[sc] & 0x1f
    if (t === 7) sps = u
    if (t === 8) pps = u
  }
  if (sps && pps) return { sps, pps }
  return null
}

function buildAvcC(spsAnnexB: Uint8Array, ppsAnnexB: Uint8Array): Uint8Array {
  const sps = stripStartCode(spsAnnexB)
  const pps = stripStartCode(ppsAnnexB)
  const len = 7 + 2 + sps.length + 2 + pps.length
  const out = new Uint8Array(len)
  let o = 0
  out[o++] = 1
  out[o++] = sps[1]
  out[o++] = sps[2]
  out[o++] = sps[3]
  out[o++] = 0xfc | 3
  out[o++] = 0xe1
  out[o++] = (sps.length >> 8) & 0xff
  out[o++] = sps.length & 0xff
  out.set(sps, o)
  o += sps.length
  out[o++] = 1
  out[o++] = (pps.length >> 8) & 0xff
  out[o++] = pps.length & 0xff
  out.set(pps, o)
  return out
}

function readU64LE(view: DataView, offset: number): number {
  const lo = view.getUint32(offset, true)
  const hi = view.getUint32(offset + 4, true)
  return lo + hi * 0x100000000
}

/** Chrome WebCodecs H.264 expects length-prefixed NALs (AVCC), not Annex-B start codes. */
function annexBPayloadToAvccChunk(payload: Uint8Array): Uint8Array {
  if (payload.length < 4) return payload
  const looksAnnexB =
    payload[0] === 0 &&
    payload[1] === 0 &&
    (payload[2] === 1 || (payload[2] === 0 && payload[3] === 1))
  if (!looksAnnexB) return payload

  const units = splitAnnexB(payload)
  const blocks: Uint8Array[] = []
  for (const u of units) {
    const nal = stripStartCode(u)
    if (nal.length === 0) continue
    const block = new Uint8Array(4 + nal.length)
    new DataView(block.buffer).setUint32(0, nal.length, false)
    block.set(nal, 4)
    blocks.push(block)
  }
  if (blocks.length === 0) return payload
  if (blocks.length === 1) return blocks[0]
  const total = blocks.reduce((n, b) => n + b.length, 0)
  const out = new Uint8Array(total)
  let o = 0
  for (const b of blocks) {
    out.set(b, o)
    o += b.length
  }
  return out
}

export interface UseDeviceH264Options {
  enabled: boolean
  canvasRef: RefObject<HTMLCanvasElement>
  /** After fatal stall / server error, switch UI back to JPEG */
  onGiveUp?: () => void
}

export interface UseDeviceH264Return {
  status: H264StreamStatus
  error: string | null
  /** Encoding resolution of the H.264 stream (e.g. 720×1280). */
  streamWidth: number | null
  streamHeight: number | null
  /**
   * Actual device screen resolution reported by `wm size` (e.g. 1080×2400).
   * Use these for ADB touch coordinate mapping, NOT streamWidth/streamHeight.
   * Falls back to streamWidth/streamHeight when not yet received.
   */
  deviceWidth: number | null
  deviceHeight: number | null
  sendControl: (msg: object) => void
  isConnected: boolean
  reconnect: () => void
}

export function useDeviceH264(
  deviceId: number | null,
  options: UseDeviceH264Options
): UseDeviceH264Return {
  const { enabled, canvasRef, onGiveUp } = options
  const wsRef = useRef<WebSocket | null>(null)
  const decoderRef = useRef<VideoDecoder | null>(null)
  const [status, setStatus] = useState<H264StreamStatus>('idle')
  const [error, setError] = useState<string | null>(null)
  const [streamWidth, setStreamWidth] = useState<number | null>(null)
  const [streamHeight, setStreamHeight] = useState<number | null>(null)
  const [deviceWidth, setDeviceWidth] = useState<number | null>(null)
  const [deviceHeight, setDeviceHeight] = useState<number | null>(null)
  const mountedRef = useRef(true)
  const enabledRef = useRef(enabled)
  enabledRef.current = enabled
  const reconnectAttemptRef = useRef(0)
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const closeDecoder = useCallback(() => {
    try {
      decoderRef.current?.close()
    } catch {
      /* already closed */
    }
    decoderRef.current = null
  }, [])

  const disconnect = useCallback(() => {
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current)
      reconnectTimerRef.current = null
    }
    if (wsRef.current) {
      const ws = wsRef.current
      wsRef.current = null
      ws.onerror = null
      ws.onmessage = null
      ws.onclose = null
      ws.close()
    }
    closeDecoder()
    setStreamWidth(null)
    setStreamHeight(null)
    setDeviceWidth(null)
    setDeviceHeight(null)
    setStatus('idle')
  }, [closeDecoder])

  const connect = useCallback(() => {
    if (!deviceId || !enabled || !mountedRef.current) return
    const cur = wsRef.current
    if (
      cur &&
      (cur.readyState === WebSocket.OPEN || cur.readyState === WebSocket.CONNECTING)
    ) {
      return
    }
    if (typeof VideoDecoder === 'undefined') {
      setError('VideoDecoder (WebCodecs) غير متاح')
      setStatus('error')
      return
    }

    const url = getWebSocketH264Url(deviceId)
    setStatus('connecting')
    setError(null)

    const ws = new WebSocket(url)
    ws.binaryType = 'arraybuffer'
    wsRef.current = ws

    ws.onopen = () => {
      if (!mountedRef.current) return
      setStatus('connected')
      reconnectAttemptRef.current = 0
    }

    ws.onmessage = (ev) => {
      if (!mountedRef.current) return
      if (typeof ev.data === 'string') {
        try {
          const j = JSON.parse(ev.data) as {
            type?: string
            message?: string
            device_width?: number
            device_height?: number
          }
          if (j.type === 'h264_error') {
            setError(j.message ?? 'فشل بث H.264')
            setStatus('error')
            onGiveUp?.()
          } else if (j.type === 'device_size' && j.device_width && j.device_height) {
            // Actual device screen resolution (e.g. 1080×2400) — used for touch
            // coordinate mapping; distinct from stream encoding size (720×1280).
            setDeviceWidth(j.device_width)
            setDeviceHeight(j.device_height)
          }
        } catch {
          /* ignore non-JSON */
        }
        return
      }

      const buf = ev.data as ArrayBuffer
      if (buf.byteLength < 1) return
      const view = new DataView(buf)
      const typ = view.getUint8(0)

      if (typ === MSG_CONFIG) {
        if (buf.byteLength < 11) return
        const width = view.getUint32(1, true)
        const height = view.getUint32(5, true)
        const codecLen = view.getUint16(9, true)
        const payloadStart = 11 + codecLen
        if (buf.byteLength < payloadStart || codecLen < 0) return
        const te = new TextDecoder()
        const codec = te.decode(new Uint8Array(buf, 11, codecLen))
        const spsPps = new Uint8Array(buf, payloadStart)
        const pair = findSpsPps(spsPps)
        closeDecoder()
        setStreamWidth(width)
        setStreamHeight(height)

        const canvas = canvasRef.current
        if (canvas) {
          canvas.width = width
          canvas.height = height
        }

        if (!pair) {
          setError('لم يُستخرج SPS/PPS')
          return
        }

        let description: Uint8Array
        try {
          description = buildAvcC(pair.sps, pair.pps)
        } catch {
          setError('فشل بناء AVCDecoderConfigurationRecord')
          return
        }

        try {
          const dec = new VideoDecoder({
            output: (frame: VideoFrame) => {
              const c = canvasRef.current
              if (c) {
                const ctx = c.getContext('2d')
                if (ctx) {
                  ctx.drawImage(frame, 0, 0, c.width, c.height)
                }
              }
              frame.close()
            },
            error: (e) => {
              console.warn('VideoDecoder error', e)
              setError(e?.message ? `فك ترميز الفيديو: ${e.message}` : 'فك ترميز الفيديو فشل')
              setStatus('error')
            },
          })
          dec.configure({
            codec: codec || 'avc1.640028',
            codedWidth: width,
            codedHeight: height,
            description,
          })
          decoderRef.current = dec
        } catch (e) {
          setError(String(e))
          setStatus('error')
        }
        return
      }

      if (typ === MSG_FRAME) {
        if (buf.byteLength < 10) return
        const flags = view.getUint8(1)
        const key = (flags & 1) !== 0
        const pts = readU64LE(view, 2)
        const raw = new Uint8Array(buf, 10)
        const dec = decoderRef.current
        if (!dec || dec.state === 'closed') return
        try {
          const data = annexBPayloadToAvccChunk(raw)
          const chunk = new EncodedVideoChunk({
            type: key ? 'key' : 'delta',
            timestamp: pts,
            data,
          })
          dec.decode(chunk)
        } catch {
          /* drop corrupt frame */
        }
      }
    }

    ws.onerror = () => {
      if (!mountedRef.current) return
      setError('خطأ WebSocket H.264')
      setStatus('error')
    }

    ws.onclose = () => {
      if (!mountedRef.current) return
      wsRef.current = null
      closeDecoder()
      setStreamWidth(null)
      setStreamHeight(null)
      setDeviceWidth(null)
      setDeviceHeight(null)
      if (!enabledRef.current) {
        setStatus('idle')
        return
      }
      setStatus('idle')
      const attempt = reconnectAttemptRef.current
      const delay = Math.min(BASE_DELAY_MS * Math.pow(2, attempt), MAX_BACKOFF_MS)
      reconnectAttemptRef.current = attempt + 1
      reconnectTimerRef.current = setTimeout(() => {
        if (mountedRef.current && enabledRef.current) {
          connect()
        }
      }, delay)
    }
  }, [deviceId, enabled, canvasRef, closeDecoder, onGiveUp])

  useEffect(() => {
    if (!enabled || status !== 'connected') return
    if (streamWidth != null) return
    const t = window.setTimeout(() => {
      if (!mountedRef.current || !enabledRef.current) return
      setError('لم يصل تكوين الفيديو (SPS/PPS) — التبديل إلى JPEG')
      setStatus('error')
      onGiveUp?.()
    }, 22_000)
    return () => window.clearTimeout(t)
  }, [enabled, status, streamWidth, onGiveUp])

  const sendControl = useCallback((msg: object) => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(msg))
    }
  }, [])

  const reconnect = useCallback(() => {
    disconnect()
    reconnectAttemptRef.current = 0
    setTimeout(() => {
      if (mountedRef.current && enabled) connect()
    }, 100)
  }, [connect, disconnect, enabled])

  useEffect(() => {
    mountedRef.current = true
    if (deviceId && enabled) {
      connect()
    } else {
      disconnect()
    }
    return () => {
      mountedRef.current = false
      disconnect()
    }
  }, [deviceId, enabled, connect, disconnect])

  return {
    status,
    error,
    streamWidth,
    streamHeight,
    deviceWidth,
    deviceHeight,
    sendControl,
    isConnected: status === 'connected',
    reconnect,
  }
}
