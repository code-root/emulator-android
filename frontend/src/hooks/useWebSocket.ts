import { useCallback, useEffect, useRef, useState } from 'react'
import type { LiveScreenshotFrame, WSMessage } from '../types'
import { getWebSocketUrl } from '../api/client'

type WSStatus = 'connecting' | 'connected' | 'disconnected' | 'error'

interface UseWebSocketReturn {
  status: WSStatus
  lastMessage: WSMessage | null
  liveScreenshot: LiveScreenshotFrame | null
  /** نص تحذير من الخادم عندما لا يظهر الجهاز في ADB أثناء بث JPEG */
  adbUnavailable: string | null
  sendMessage: (msg: object) => void
  isConnected: boolean
  reconnect: () => void
}

const MAX_BACKOFF_MS = 30_000
const BASE_DELAY_MS = 1_000

export function useWebSocket(
  deviceId: number | null,
  options?: { enabled?: boolean }
): UseWebSocketReturn {
  const enabled = options?.enabled !== false
  const wsRef = useRef<WebSocket | null>(null)
  const [status, setStatus] = useState<WSStatus>('disconnected')
  const [lastMessage, setLastMessage] = useState<WSMessage | null>(null)
  const [liveScreenshot, setLiveScreenshot] = useState<LiveScreenshotFrame | null>(null)
  const [adbUnavailable, setAdbUnavailable] = useState<string | null>(null)
  const reconnectAttemptRef = useRef(0)
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const mountedRef = useRef(true)

  const connect = useCallback(() => {
    if (!deviceId || !enabled || !mountedRef.current) return
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) return

    const url = getWebSocketUrl(deviceId)
    setStatus('connecting')

    const ws = new WebSocket(url)
    wsRef.current = ws

    ws.onopen = () => {
      if (!mountedRef.current) return
      setStatus('connected')
      setLiveScreenshot(null)
      setAdbUnavailable(null)
      reconnectAttemptRef.current = 0
    }

    ws.onmessage = (event) => {
      if (!mountedRef.current) return
      try {
        const msg: WSMessage = JSON.parse(event.data)
        setLastMessage(msg)
        if (msg.type === 'adb_unavailable') {
          setAdbUnavailable(
            typeof msg.message === 'string' && msg.message.length
              ? msg.message
              : 'ADB غير متاح'
          )
        } else if (msg.type === 'screenshot' && msg.data) {
          setAdbUnavailable(null)
          const w = typeof msg.width === 'number' ? msg.width : 1080
          const h = typeof msg.height === 'number' ? msg.height : 1920
          const dw =
            typeof msg.device_width === 'number' ? msg.device_width : w
          const dh =
            typeof msg.device_height === 'number' ? msg.device_height : h
          const fmt = (msg.format || 'png').toLowerCase()
          const mimeType = fmt === 'jpeg' || fmt === 'jpg' ? 'image/jpeg' : 'image/png'
          setLiveScreenshot({
            dataBase64: msg.data,
            width: w,
            height: h,
            deviceWidth: dw,
            deviceHeight: dh,
            mimeType,
          })
        }
      } catch {
        // non-JSON message
      }
    }

    ws.onerror = () => {
      if (!mountedRef.current) return
      setStatus('error')
    }

    ws.onclose = () => {
      if (!mountedRef.current) return
      setStatus('disconnected')
      wsRef.current = null

      // Exponential backoff reconnect
      const attempt = reconnectAttemptRef.current
      const delay = Math.min(BASE_DELAY_MS * Math.pow(2, attempt), MAX_BACKOFF_MS)
      reconnectAttemptRef.current = attempt + 1

      reconnectTimerRef.current = setTimeout(() => {
        if (mountedRef.current) {
          connect()
        }
      }, delay)
    }
  }, [deviceId, enabled])

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
    setStatus('disconnected')
    setAdbUnavailable(null)
  }, [])

  const reconnect = useCallback(() => {
    disconnect()
    reconnectAttemptRef.current = 0
    setTimeout(connect, 100)
  }, [connect, disconnect])

  const sendMessage = useCallback((msg: object) => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(msg))
    }
  }, [])

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
    lastMessage,
    liveScreenshot,
    adbUnavailable,
    sendMessage,
    isConnected: status === 'connected',
    reconnect,
  }
}

export { useDeviceH264 } from './useDeviceH264'
