import { useState, useRef, useEffect, useLayoutEffect, useCallback } from 'react'
import type { RefObject } from 'react'
import {
  Loader2,
  RefreshCw,
  MousePointer,
  Hand,
  Sparkles,
  Maximize2,
  Minimize2,
  Radio,
  Zap,
  Type,
} from 'lucide-react'
import { getScreenshot } from '../api/client'
import type { LiveScreenshotFrame } from '../types'
import type { H264StreamStatus } from '../hooks/useDeviceH264'
import clsx from 'clsx'

const FPS_PRESETS_MS = [
  { label: 'أقصى سرعة 0ms (افتراضي)', ms: 0 },
  { label: '0.001 ث (1ms)', ms: 1 },
  { label: '~20 إطار/ث', ms: 50 },
  { label: '~15', ms: 66 },
  { label: '~12', ms: 80 },
  { label: '~8', ms: 125 },
  { label: 'موفر', ms: 350 },
] as const

/** مقاطع السحب: مدة أقل من ~10ms غالباً تُهمل على أندرويد؛ اللمس قد لا يضبط buttons أثناء الحركة. */
const DRAG_MIN_DEVICE_PX = 2
const DRAG_SEGMENT_MIN_INTERVAL_MS = 6
const DRAG_SEGMENT_DURATION_MS = 25
const DRAG_FINAL_SEGMENT_DURATION_MS = 80
const DRAG_FALLBACK_SWIPE_MS = 280
/** وضع تلقائي: حركة أقل من هذا (بكسل الجهاز) بدون مقاطع سحب = يُعامل كلمسة. */
const AUTO_TAP_MAX_MOVE_SQ = 20 * 20

function clientToDevicePixel(
  el: HTMLImageElement,
  shot: LiveScreenshotFrame | null,
  clientX: number,
  clientY: number
): { x: number; y: number } {
  const rect = el.getBoundingClientRect()
  const devW = shot?.deviceWidth ?? el.naturalWidth ?? 1080
  const devH = shot?.deviceHeight ?? el.naturalHeight ?? 1920
  const nx = Math.min(1, Math.max(0, (clientX - rect.left) / rect.width))
  const ny = Math.min(1, Math.max(0, (clientY - rect.top) / rect.height))
  return { x: Math.round(nx * devW), y: Math.round(ny * devH) }
}

function clientToDeviceSurface(
  el: HTMLElement,
  shot: LiveScreenshotFrame | null,
  streamW: number | null,
  streamH: number | null,
  mode: 'jpeg' | 'h264',
  clientX: number,
  clientY: number
): { x: number; y: number } {
  const rect = el.getBoundingClientRect()
  let devW = 1080
  let devH = 1920
  if (mode === 'jpeg' && shot) {
    devW = shot.deviceWidth ?? shot.width
    devH = shot.deviceHeight ?? shot.height
  } else if (mode === 'h264' && streamW && streamH) {
    devW = streamW
    devH = streamH
  } else if (el instanceof HTMLImageElement) {
    devW = el.naturalWidth || 1080
    devH = el.naturalHeight || 1920
  } else if (el instanceof HTMLCanvasElement) {
    devW = el.width || 1080
    devH = el.height || 1920
  } else {
    const nested = el.querySelector('canvas')
    if (nested) {
      devW = nested.width || 1080
      devH = nested.height || 1920
    }
  }
  const nx = Math.min(1, Math.max(0, (clientX - rect.left) / rect.width))
  const ny = Math.min(1, Math.max(0, (clientY - rect.top) / rect.height))
  return { x: Math.round(nx * devW), y: Math.round(ny * devH) }
}

interface DeviceScreenProps {
  deviceId: number
  serial: string | null
  isRunning: boolean
  sendControl: (msg: object) => void
  controlConnected: boolean
  jpegConnected: boolean
  liveScreenshot: LiveScreenshotFrame | null
  /** تحذير من WebSocket عند فقدان الجهاز في ADB أثناء البث */
  adbUnavailable?: string | null
  screenStreamMode: 'jpeg' | 'h264'
  onScreenStreamModeChange: (m: 'jpeg' | 'h264') => void
  h264CanvasRef: RefObject<HTMLCanvasElement>
  h264StreamWidth: number | null
  h264StreamHeight: number | null
  h264Error: string | null
  h264Status: H264StreamStatus
}

export default function DeviceScreen({
  deviceId,
  serial,
  isRunning,
  sendControl,
  controlConnected,
  jpegConnected,
  liveScreenshot,
  adbUnavailable = null,
  screenStreamMode,
  onScreenStreamModeChange,
  h264CanvasRef,
  h264StreamWidth,
  h264StreamHeight,
  h264Error,
  h264Status,
}: DeviceScreenProps) {
  const [staticUrl, setStaticUrl] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [liveMirror, setLiveMirror] = useState(true)
  const [intervalMs, setIntervalMs] = useState(0)
  const [liveBlobUrl, setLiveBlobUrl] = useState<string | null>(null)
  const [isDragging, setIsDragging] = useState(false)
  const [dragStart, setDragStart] = useState({ x: 0, y: 0 })
  const [mode, setMode] = useState<'tap' | 'swipe' | 'auto'>('auto')
  const [displayScale, setDisplayScale] = useState(100)
  const [textDraft, setTextDraft] = useState('')
  const [fullscreenActive, setFullscreenActive] = useState(false)
  const imgRef = useRef<HTMLImageElement>(null)
  /** طبقة لمس فوق canvas في وضع H.264 (بعض المتصفحات تُخفق في تسليم PointerEvent للـ canvas) */
  const h264TouchLayerRef = useRef<HTMLDivElement>(null)
  const stageRef = useRef<HTMLDivElement>(null)
  const liveCapUrlRef = useRef<string | null>(null)
  const liveShotRef = useRef<LiveScreenshotFrame | null>(null)
  liveShotRef.current = liveScreenshot

  const dragStartRef = useRef({ x: 0, y: 0 })
  const lastEmittedRef = useRef({ x: 0, y: 0 })
  const segmentsSentRef = useRef(0)
  const isDraggingRef = useRef(false)
  const pendingPointerRef = useRef<{ clientX: number; clientY: number } | null>(null)
  const lastDragSegmentAtRef = useRef(0)
  const activePointerIdRef = useRef<number | null>(null)
  const pointerSessionRef = useRef(false)
  const modeRef = useRef(mode)
  modeRef.current = mode
  const lastClientRef = useRef({ clientX: 0, clientY: 0 })
  const endGestureRef = useRef<(cx: number, cy: number, pointerId: number) => void>(() => {})

  const sendMessageRef = useRef(sendControl)
  sendMessageRef.current = sendControl
  const isConnectedRef = useRef(controlConnected)
  isConnectedRef.current = controlConnected
  const isRunningRef = useRef(isRunning)
  isRunningRef.current = isRunning

  useEffect(() => {
    const onFs = () => setFullscreenActive(!!document.fullscreenElement)
    document.addEventListener('fullscreenchange', onFs)
    return () => document.removeEventListener('fullscreenchange', onFs)
  }, [])

  const fetchStatic = useCallback(async () => {
    if (!isRunning || !serial || screenStreamMode === 'h264') return
    setLoading(true)
    setError(null)
    try {
      const blob = await getScreenshot(deviceId)
      const url = URL.createObjectURL(blob)
      setStaticUrl((old) => {
        if (old) URL.revokeObjectURL(old)
        return url
      })
    } catch (e) {
      setError(e instanceof Error ? e.message : 'تعذر التقاط الشاشة')
    } finally {
      setLoading(false)
    }
  }, [deviceId, isRunning, serial, screenStreamMode])

  useEffect(() => {
    if (isRunning && screenStreamMode === 'jpeg') fetchStatic()
  }, [isRunning, screenStreamMode, fetchStatic])

  useEffect(() => {
    if (!isRunning || !jpegConnected || screenStreamMode !== 'jpeg') return
    if (liveMirror) {
      sendControl({
        action: 'subscribe_screenshots',
        interval_ms: intervalMs,
        stream_mode: 'jpeg',
      })
    } else {
      sendControl({ action: 'unsubscribe_screenshots' })
    }
    return () => {
      sendControl({ action: 'unsubscribe_screenshots' })
    }
  }, [
    isRunning,
    jpegConnected,
    screenStreamMode,
    liveMirror,
    intervalMs,
    sendControl,
  ])

  useEffect(() => {
    if (!liveMirror || !liveScreenshot?.dataBase64) {
      if (liveCapUrlRef.current) {
        URL.revokeObjectURL(liveCapUrlRef.current)
        liveCapUrlRef.current = null
      }
      setLiveBlobUrl(null)
      return
    }
    try {
      const bin = atob(liveScreenshot.dataBase64)
      const u8 = new Uint8Array(bin.length)
      for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i)
      const blob = new Blob([u8], { type: 'image/png' })
      const url = URL.createObjectURL(blob)
      const prev = liveCapUrlRef.current
      liveCapUrlRef.current = url
      setLiveBlobUrl(url)
      if (prev) URL.revokeObjectURL(prev)
    } catch {
      if (liveCapUrlRef.current) {
        URL.revokeObjectURL(liveCapUrlRef.current)
        liveCapUrlRef.current = null
      }
      setLiveBlobUrl(null)
    }
  }, [liveMirror, liveScreenshot?.dataBase64, liveScreenshot?.mimeType])

  useEffect(
    () => () => {
      if (liveCapUrlRef.current) {
        URL.revokeObjectURL(liveCapUrlRef.current)
        liveCapUrlRef.current = null
      }
    },
    []
  )

  /** إنهاء الإيماءة من window/visibility إذا ضاعت أحداث target (سحب خارج اللوحة، تبديل تبويب، إلخ). */
  useEffect(() => {
    const onWinPointerEnd = (ev: PointerEvent) => {
      if (!pointerSessionRef.current || ev.pointerId !== activePointerIdRef.current) return
      endGestureRef.current(ev.clientX, ev.clientY, ev.pointerId)
    }
    window.addEventListener('pointerup', onWinPointerEnd, true)
    window.addEventListener('pointercancel', onWinPointerEnd, true)
    return () => {
      window.removeEventListener('pointerup', onWinPointerEnd, true)
      window.removeEventListener('pointercancel', onWinPointerEnd, true)
    }
  }, [])

  useEffect(() => {
    const onVis = () => {
      if (document.visibilityState !== 'hidden') return
      if (!pointerSessionRef.current || activePointerIdRef.current == null) return
      const { clientX, clientY } = lastClientRef.current
      endGestureRef.current(clientX, clientY, activePointerIdRef.current)
    }
    document.addEventListener('visibilitychange', onVis)
    return () => document.removeEventListener('visibilitychange', onVis)
  }, [])

  const displaySrc = liveMirror && liveBlobUrl ? liveBlobUrl : staticUrl

  function getSurfaceEl(): HTMLElement | null {
    if (screenStreamMode === 'h264') return h264TouchLayerRef.current
    return imgRef.current
  }

  function getRelativeCoords(clientX: number, clientY: number): { x: number; y: number } {
    const el = getSurfaceEl()
    if (!el) return { x: 0, y: 0 }
    if (screenStreamMode === 'jpeg' && el instanceof HTMLImageElement) {
      return clientToDevicePixel(el, liveShotRef.current, clientX, clientY)
    }
    return clientToDeviceSurface(
      el,
      liveShotRef.current,
      h264StreamWidth,
      h264StreamHeight,
      screenStreamMode,
      clientX,
      clientY
    )
  }

  function flushDragSegment(): boolean {
    if (!isConnectedRef.current || !isRunningRef.current) return false
    const p = pendingPointerRef.current
    if (!p) return false
    const el = getSurfaceEl()
    if (!el) return false
    const cur =
      screenStreamMode === 'jpeg' && el instanceof HTMLImageElement
        ? clientToDevicePixel(el, liveShotRef.current, p.clientX, p.clientY)
        : clientToDeviceSurface(
            el,
            liveShotRef.current,
            h264StreamWidth,
            h264StreamHeight,
            screenStreamMode,
            p.clientX,
            p.clientY
          )
    const last = lastEmittedRef.current
    const dx = cur.x - last.x
    const dy = cur.y - last.y
    if (dx * dx + dy * dy < DRAG_MIN_DEVICE_PX * DRAG_MIN_DEVICE_PX) return false
    sendMessageRef.current({
      action: 'swipe',
      x1: last.x,
      y1: last.y,
      x2: cur.x,
      y2: cur.y,
      duration_ms: DRAG_SEGMENT_DURATION_MS,
    })
    lastEmittedRef.current = cur
    segmentsSentRef.current += 1
    return true
  }

  /** إرسال مقطع إن تحرك الإصبع كفاية وبعد فاصل زمني (لحظي أكثر من إطار واحد/ث). */
  function tryEmitDragSegmentThrottled() {
    const now = performance.now()
    if (now - lastDragSegmentAtRef.current < DRAG_SEGMENT_MIN_INTERVAL_MS) return
    if (flushDragSegment()) {
      lastDragSegmentAtRef.current = now
    }
  }

  /** pointerrawupdate غير مُعرَّف في أنواع React لـ <img> — نربطه يدوياً لعيّنة أدق على قلم/لمس. */
  useLayoutEffect(() => {
    const el =
      screenStreamMode === 'h264' ? h264TouchLayerRef.current : imgRef.current
    if (!el) return
    const onRaw = (ev: Event) => {
      if (!(ev instanceof PointerEvent)) return
      if (!pointerSessionRef.current) return
      if (!isConnectedRef.current || !isRunningRef.current) return
      if (ev.pointerId !== activePointerIdRef.current) return
      if (ev.pointerType === 'mouse' && (ev.buttons & 1) === 0) return
      lastClientRef.current = { clientX: ev.clientX, clientY: ev.clientY }
      pendingPointerRef.current = { clientX: ev.clientX, clientY: ev.clientY }
      if (!isDraggingRef.current) {
        isDraggingRef.current = true
        setIsDragging(true)
      }
      tryEmitDragSegmentThrottled()
    }
    el.addEventListener('pointerrawupdate', onRaw)
    return () => el.removeEventListener('pointerrawupdate', onRaw)
  }, [
    displaySrc,
    screenStreamMode,
    h264StreamWidth,
    h264StreamHeight,
    h264Status,
  ])

  function onPointerDown(e: React.PointerEvent<HTMLElement>) {
    if (!controlConnected || !isRunning) return
    e.preventDefault()
    pointerSessionRef.current = true
    activePointerIdRef.current = e.pointerId
    lastClientRef.current = { clientX: e.clientX, clientY: e.clientY }
    ;(e.target as HTMLElement).setPointerCapture?.(e.pointerId)
    const { x, y } = getRelativeCoords(e.clientX, e.clientY)
    dragStartRef.current = { x, y }
    lastEmittedRef.current = { x, y }
    segmentsSentRef.current = 0
    isDraggingRef.current = false
    pendingPointerRef.current = null
    lastDragSegmentAtRef.current = 0
    setDragStart({ x, y })
    setIsDragging(false)
  }

  function onPointerMove(e: React.PointerEvent<HTMLElement>) {
    if (!controlConnected || !isRunning) return
    if (e.pointerId !== activePointerIdRef.current) return
    // أثناء اللمس قد يكون buttons=0 في WebKit رغم استمرار الإصبع — نعتمد pointer capture + pointerId
    if (e.pointerType === 'mouse' && (e.buttons & 1) === 0) return
    isDraggingRef.current = true
    setIsDragging(true)
    lastClientRef.current = { clientX: e.clientX, clientY: e.clientY }
    pendingPointerRef.current = { clientX: e.clientX, clientY: e.clientY }
    tryEmitDragSegmentThrottled()
  }

  function finalizeAtClient(clientX: number, clientY: number, pointerId: number) {
    if (!pointerSessionRef.current) return
    if (pointerId !== activePointerIdRef.current) return
    pointerSessionRef.current = false
    activePointerIdRef.current = null
    const surf = getSurfaceEl()
    if (surf?.releasePointerCapture) {
      try {
        surf.releasePointerCapture(pointerId)
      } catch {
        /* قد يُطلق تلقائياً */
      }
    }

    const dragged = isDraggingRef.current
    isDraggingRef.current = false
    setIsDragging(false)

    if (!isConnectedRef.current || !isRunningRef.current) return

    lastClientRef.current = { clientX, clientY }
    pendingPointerRef.current = { clientX, clientY }
    flushDragSegment()
    pendingPointerRef.current = null

    const end = getRelativeCoords(clientX, clientY)
    const start = dragStartRef.current
    const moveSq =
      (end.x - start.x) * (end.x - start.x) + (end.y - start.y) * (end.y - start.y)
    const autoAsTap =
      modeRef.current === 'auto' &&
      segmentsSentRef.current === 0 &&
      moveSq <= AUTO_TAP_MAX_MOVE_SQ

    if (autoAsTap || (modeRef.current === 'tap' && !dragged)) {
      sendMessageRef.current({ action: 'tap', x: end.x, y: end.y })
    } else if (segmentsSentRef.current > 0) {
      const last = lastEmittedRef.current
      const dx = end.x - last.x
      const dy = end.y - last.y
      if (dx !== 0 || dy !== 0) {
        sendMessageRef.current({
          action: 'swipe',
          x1: last.x,
          y1: last.y,
          x2: end.x,
          y2: end.y,
          duration_ms: DRAG_FINAL_SEGMENT_DURATION_MS,
        })
      }
    } else if (modeRef.current === 'swipe' || dragged || modeRef.current === 'auto') {
      sendMessageRef.current({
        action: 'swipe',
        x1: start.x,
        y1: start.y,
        x2: end.x,
        y2: end.y,
        duration_ms: DRAG_FALLBACK_SWIPE_MS,
      })
    }
  }

  endGestureRef.current = finalizeAtClient

  function finalizePointer(e: React.PointerEvent<HTMLElement>) {
    finalizeAtClient(e.clientX, e.clientY, e.pointerId)
  }

  function onPointerUp(e: React.PointerEvent<HTMLElement>) {
    finalizePointer(e)
  }

  function onPointerCancel(e: React.PointerEvent<HTMLElement>) {
    finalizePointer(e)
  }

  function onLostPointerCapture(e: React.PointerEvent<HTMLElement>) {
    if (!pointerSessionRef.current) return
    finalizePointer(e)
  }

  function sendKeyEvent(key: string) {
    sendControl({ action: 'keyevent', key })
  }

  function sendTypedText() {
    if (!textDraft.trim()) return
    sendControl({ action: 'input_text', text: textDraft })
    setTextDraft('')
  }

  const toggleFullscreen = () => {
    const el = stageRef.current
    if (!el) return
    if (!document.fullscreenElement) {
      el.requestFullscreen?.().catch(() => {})
    } else {
      document.exitFullscreen?.()
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2 gap-y-3">
        <div className="flex items-center gap-1 bg-gray-800/80 rounded-lg p-1 border border-gray-700">
          <button
            type="button"
            onClick={() => onScreenStreamModeChange('h264')}
            disabled={!isRunning || typeof VideoDecoder === 'undefined'}
            className={clsx(
              'px-2 py-1 rounded text-xs font-medium',
              screenStreamMode === 'h264'
                ? 'bg-emerald-600 text-white'
                : 'text-gray-400 hover:text-gray-200'
            )}
          >
            H.264
          </button>
          <button
            type="button"
            onClick={() => onScreenStreamModeChange('jpeg')}
            disabled={!isRunning}
            className={clsx(
              'px-2 py-1 rounded text-xs font-medium',
              screenStreamMode === 'jpeg'
                ? 'bg-emerald-600 text-white'
                : 'text-gray-400 hover:text-gray-200'
            )}
          >
            JPEG
          </button>
        </div>

        <button
          type="button"
          onClick={() => setLiveMirror((v) => !v)}
          disabled={!isRunning || !jpegConnected || screenStreamMode === 'h264'}
          className={clsx(
            'btn-sm flex items-center gap-1.5',
            liveMirror ? 'btn-primary' : 'btn-secondary'
          )}
        >
          <Radio className="w-3.5 h-3.5" />
          {screenStreamMode === 'h264'
            ? 'بث H.264'
            : liveMirror
              ? 'بث مباشر'
              : 'بث متوقف'}
        </button>

        <div className="flex items-center gap-1.5 flex-wrap">
          <Zap className="w-3.5 h-3.5 text-amber-400 shrink-0" />
          <span className="text-xs text-gray-500">معدل:</span>
          {FPS_PRESETS_MS.map((p) => (
            <button
              key={p.ms}
              type="button"
              disabled={
                !isRunning ||
                !jpegConnected ||
                !liveMirror ||
                screenStreamMode === 'h264'
              }
              onClick={() => setIntervalMs(p.ms)}
              className={clsx(
                'px-2 py-1 rounded text-xs font-medium transition-colors',
                intervalMs === p.ms
                  ? 'bg-amber-600/90 text-white'
                  : 'bg-gray-800 text-gray-400 hover:text-gray-200'
              )}
            >
              {p.label}
            </button>
          ))}
        </div>

        <div className="flex items-center gap-2 text-xs text-gray-400">
          <span>تكبير</span>
          <input
            type="range"
            min={70}
            max={160}
            value={displayScale}
            onChange={(e) => setDisplayScale(Number(e.target.value))}
            className="w-24 accent-blue-500"
          />
          <span className="tabular-nums w-9">{displayScale}%</span>
        </div>

        <button
          type="button"
          onClick={fetchStatic}
          disabled={!isRunning || loading}
          className="btn-secondary btn-sm"
        >
          <RefreshCw className={clsx('w-3.5 h-3.5', loading && 'animate-spin')} />
          لقطة
        </button>

        <button
          type="button"
          onClick={toggleFullscreen}
          disabled={!isRunning}
          className="btn-secondary btn-sm flex items-center gap-1"
        >
          {fullscreenActive ? (
            <Minimize2 className="w-3.5 h-3.5" />
          ) : (
            <Maximize2 className="w-3.5 h-3.5" />
          )}
          ملء الشاشة
        </button>

        <div className="flex gap-1 bg-gray-800/80 rounded-lg p-1 border border-gray-700">
          <button
            type="button"
            onClick={() => setMode('tap')}
            className={clsx(
              'flex items-center gap-1 px-2 py-1 rounded text-xs font-medium',
              mode === 'tap' ? 'bg-blue-600 text-white' : 'text-gray-400 hover:text-gray-200'
            )}
          >
            <MousePointer className="w-3.5 h-3.5" /> لمس
          </button>
          <button
            type="button"
            onClick={() => setMode('swipe')}
            className={clsx(
              'flex items-center gap-1 px-2 py-1 rounded text-xs font-medium',
              mode === 'swipe' ? 'bg-blue-600 text-white' : 'text-gray-400 hover:text-gray-200'
            )}
          >
            <Hand className="w-3.5 h-3.5" /> سحب
          </button>
          <button
            type="button"
            onClick={() => setMode('auto')}
            title="لمسة قصيرة = نقرة؛ حركة أوضح = سحب"
            className={clsx(
              'flex items-center gap-1 px-2 py-1 rounded text-xs font-medium',
              mode === 'auto' ? 'bg-blue-600 text-white' : 'text-gray-400 hover:text-gray-200'
            )}
          >
            <Sparkles className="w-3.5 h-3.5" /> تلقائي
          </button>
        </div>

        <div className="flex gap-1 ml-auto flex-wrap justify-end">
          {[
            { label: '◀', key: 'KEYCODE_BACK', title: 'رجوع' },
            { label: '⌂', key: 'KEYCODE_HOME', title: 'الرئيسية' },
            { label: '▣', key: 'KEYCODE_APP_SWITCH', title: 'التطبيقات' },
            { label: '⏻', key: 'KEYCODE_POWER', title: 'طاقة' },
          ].map((btn) => (
            <button
              key={btn.key}
              type="button"
              title={btn.title}
              onClick={() => sendKeyEvent(btn.key)}
              disabled={!isRunning || !controlConnected}
              className="btn-secondary btn-sm w-9 justify-center text-base"
            >
              {btn.label}
            </button>
          ))}
        </div>
      </div>

      <div className="flex flex-wrap items-end gap-2">
        <div className="relative flex-1 min-w-[200px] max-w-md">
          <span className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500">
            <Type className="w-3.5 h-3.5" />
          </span>
          <input
            className="input pl-9 text-sm"
            placeholder="نص إلى الجهاز (حقل نشط على الشاشة)"
            value={textDraft}
            disabled={!isRunning || !controlConnected}
            onChange={(e) => setTextDraft(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && sendTypedText()}
          />
        </div>
        <button
          type="button"
          onClick={sendTypedText}
          disabled={!isRunning || !controlConnected || !textDraft.trim()}
          className="btn-primary btn-sm"
        >
          إرسال نص
        </button>
      </div>

      <div
        ref={stageRef}
        className="relative rounded-2xl overflow-hidden bg-black border border-gray-700/80 shadow-2xl mx-auto"
        style={{
          width: '100%',
          maxWidth: 'min(100%, 920px)',
          minHeight: 'min(85vh, 900px)',
        }}
      >
        {adbUnavailable && screenStreamMode === 'jpeg' ? (
          <div className="absolute top-0 left-0 right-0 z-20 px-3 py-2 bg-amber-950/95 text-amber-100 text-xs text-center border-b border-amber-800/60">
            {adbUnavailable}
          </div>
        ) : null}
        {!isRunning ? (
          <div className="absolute inset-0 flex flex-col items-center justify-center text-gray-500 min-h-[320px]">
            <p>الجهاز متوقف — اضغط Start للتحكم</p>
          </div>
        ) : loading && !displaySrc && screenStreamMode === 'jpeg' ? (
          <div className="absolute inset-0 flex items-center justify-center min-h-[320px]">
            <Loader2 className="w-10 h-10 animate-spin text-blue-400" />
          </div>
        ) : error && !displaySrc && screenStreamMode === 'jpeg' ? (
          <div className="absolute inset-0 flex items-center justify-center text-gray-500 min-h-[320px]">
            {error}
          </div>
        ) : isRunning && screenStreamMode === 'h264' ? (
          <div
            className="relative flex flex-col items-center justify-center w-full h-full p-2 sm:p-4 gap-2"
            style={{
              minHeight: 'min(85vh, 880px)',
            }}
          >
            {h264Error ? (
              <p className="text-amber-400 text-sm text-center px-4 z-10">{h264Error}</p>
            ) : null}
            <div
              style={{
                transform: `scale(${displayScale / 100})`,
                transformOrigin: 'center center',
                maxWidth: '100%',
                maxHeight: '100%',
              }}
            >
              <div
                ref={h264TouchLayerRef}
                className="relative z-[1] inline-block cursor-crosshair select-none touch-none"
                style={{
                  touchAction: 'none',
                  WebkitTouchCallout: 'none' as const,
                }}
                onPointerDown={onPointerDown}
                onPointerMove={onPointerMove}
                onPointerUp={onPointerUp}
                onPointerCancel={onPointerCancel}
                onLostPointerCapture={onLostPointerCapture}
              >
                <canvas
                  ref={h264CanvasRef}
                  className="max-w-none max-h-[82vh] w-auto h-auto block bg-black min-w-[200px] min-h-[360px] pointer-events-none"
                  style={{ imageRendering: 'auto' }}
                />
              </div>
            </div>
            {(h264Status === 'connecting' ||
              (h264Status === 'connected' && !h264StreamWidth)) &&
            !h264Error ? (
              <div
                className="absolute inset-0 z-[2] flex flex-col items-center justify-center gap-2 bg-black/40"
                style={{ pointerEvents: 'none' }}
              >
                <Loader2 className="w-10 h-10 animate-spin text-blue-400" />
                <p className="text-xs text-gray-400 px-4 text-center">
                  جاري استقبال بث H.264 من الخادم…
                </p>
              </div>
            ) : null}
          </div>
        ) : displaySrc ? (
          <div
            className="flex items-center justify-center w-full h-full p-2 sm:p-4"
            style={{
              minHeight: 'min(85vh, 880px)',
            }}
          >
            <div
              style={{
                transform: `scale(${displayScale / 100})`,
                transformOrigin: 'center center',
                maxWidth: '100%',
                maxHeight: '100%',
              }}
            >
              <img
                ref={imgRef}
                src={displaySrc}
                alt="شاشة الجهاز"
                className="max-w-none max-h-[82vh] w-auto h-auto object-contain cursor-crosshair select-none touch-none"
                style={{ imageRendering: 'auto' }}
                draggable={false}
                onPointerDown={onPointerDown}
                onPointerMove={onPointerMove}
                onPointerUp={onPointerUp}
                onPointerCancel={onPointerCancel}
                onLostPointerCapture={onLostPointerCapture}
              />
            </div>
          </div>
        ) : null}

        {loading && displaySrc && (
          <div className="absolute top-3 end-3">
            <Loader2 className="w-4 h-4 animate-spin text-blue-400 opacity-70" />
          </div>
        )}
      </div>

      {controlConnected && isRunning && (
        <p className="text-center text-xs text-gray-500 leading-relaxed">
          {screenStreamMode === 'h264'
            ? 'بث WebSocket ثنائي الاتجاه: H.264 (screenrecord) + WebCodecs — سحب يُدمج على الخادم'
            : 'بث WebSocket • سحب: دمج مقاطع على الخادم • JPEG + Blob URL'}
          {screenStreamMode === 'jpeg' && liveMirror && !liveScreenshot?.dataBase64
            ? ' — في انتظار أول إطار…'
            : ''}
        </p>
      )}
    </div>
  )
}
