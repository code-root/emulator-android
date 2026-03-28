import { useState, useEffect, useRef, useCallback } from 'react'
import { useParams, useNavigate, useLocation } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Play, Square, RotateCcw, ArrowLeft, Loader2,
  Monitor, Fingerprint, AppWindow, Shield, Terminal, ScrollText, Info, Zap
} from 'lucide-react'
import { getDevice, startDevice, stopDevice, restartDevice, executeShell, getFingerprintFull } from '../api/client'
import { useWebSocket, useDeviceH264 } from '../hooks/useWebSocket'
import DeviceScreen from '../components/DeviceScreen'
import FingerprintEditor from '../components/FingerprintEditor'
import APKInstaller from '../components/APKInstaller'
import ProxyConfig from '../components/ProxyConfig'
import FridaManager from '../components/FridaManager'
import LogsViewer from '../components/LogsViewer'
import type { DeviceStatus } from '../types'
import clsx from 'clsx'

const STATUS_BADGE: Record<DeviceStatus, string> = {
  created: 'badge-created',
  booting: 'badge-booting',
  running: 'badge-running',
  stopped: 'badge-stopped',
  error: 'badge-error',
}

type Tab = 'overview' | 'screen' | 'fingerprint' | 'apps' | 'proxy' | 'console' | 'frida' | 'logs'

const TABS: { id: Tab; label: string; icon: React.ReactNode }[] = [
  { id: 'overview', label: 'Overview', icon: <Info className="w-4 h-4" /> },
  { id: 'screen', label: 'Screen', icon: <Monitor className="w-4 h-4" /> },
  { id: 'fingerprint', label: 'Fingerprint', icon: <Fingerprint className="w-4 h-4" /> },
  { id: 'apps', label: 'Apps', icon: <AppWindow className="w-4 h-4" /> },
  { id: 'proxy', label: 'Proxy', icon: <Shield className="w-4 h-4" /> },
  { id: 'console', label: 'Console', icon: <Terminal className="w-4 h-4" /> },
  { id: 'frida', label: 'Frida', icon: <Zap className="w-4 h-4" /> },
  { id: 'logs', label: 'Logs', icon: <ScrollText className="w-4 h-4" /> },
]

function SamsungCard({ fp }: { fp: { device_model?: string | null; manufacturer?: string | null; android_version?: string | null; sdk_version?: number | null; ap_version?: string | null; csc_version?: string | null; extended?: Record<string, unknown> } }) {
  const exynos = fp.extended?.exynos as { soc?: string; cores?: number; specs?: { big_cores?: { name: string; count: number; frequency_mhz: number }; little_cores?: { name: string; count: number; frequency_mhz: number }; gpu?: { model: string; frequency_mhz: number }; memory?: { total_mb: number } } } | undefined
  const ANDROID_TO_ONEUI: Record<string, string> = { '15': '7.0', '14': '6.0', '13': '5.1', '12': '4.1', '11': '3.1' }
  const oneUiStr = ANDROID_TO_ONEUI[fp.android_version || ''] || ''

  return (
    <div className="card space-y-4">
      <div className="flex items-center gap-2 mb-1">
        <span className="text-blue-400 font-bold text-sm tracking-widest uppercase">Samsung</span>
        <span className="bg-blue-900/40 text-blue-300 text-xs px-2 py-0.5 rounded">{fp.device_model}</span>
        {oneUiStr && <span className="bg-indigo-900/40 text-indigo-300 text-xs px-2 py-0.5 rounded">One UI {oneUiStr}</span>}
        <span className="bg-green-900/40 text-green-300 text-xs px-2 py-0.5 rounded">Knox ✓</span>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* Firmware info */}
        <div className="space-y-2">
          <p className="text-xs text-gray-500 uppercase tracking-wider">Firmware</p>
          {[
            ['Model', fp.device_model],
            ['Android', fp.android_version ? `Android ${fp.android_version} (API ${fp.sdk_version})` : '—'],
            ['AP Version', fp.ap_version || '—'],
            ['CSC Version', fp.csc_version || '—'],
          ].map(([k, v]) => (
            <div key={String(k)} className="flex justify-between text-sm">
              <span className="text-gray-400">{k}</span>
              <span className="text-gray-200 font-mono text-xs">{String(v || '—')}</span>
            </div>
          ))}
        </div>

        {/* Exynos CPU */}
        <div className="space-y-2">
          <p className="text-xs text-gray-500 uppercase tracking-wider">Exynos Processor</p>
          {exynos ? (
            <>
              {[
                ['SoC', exynos.soc],
                ['Total Cores', exynos.cores],
                ['Big Cores', exynos.specs?.big_cores ? `${exynos.specs.big_cores.count}x ${exynos.specs.big_cores.name} @ ${exynos.specs.big_cores.frequency_mhz} MHz` : '—'],
                ['Little Cores', exynos.specs?.little_cores ? `${exynos.specs.little_cores.count}x ${exynos.specs.little_cores.name} @ ${exynos.specs.little_cores.frequency_mhz} MHz` : '—'],
              ].map(([k, v]) => (
                <div key={String(k)} className="flex justify-between text-sm">
                  <span className="text-gray-400">{k}</span>
                  <span className="text-gray-200 font-mono text-xs">{String(v ?? '—')}</span>
                </div>
              ))}
            </>
          ) : (
            <p className="text-xs text-gray-600">No Exynos data — create device with firmware preset</p>
          )}
        </div>

        {/* GPU */}
        <div className="space-y-2">
          <p className="text-xs text-gray-500 uppercase tracking-wider">GPU / Memory</p>
          {exynos?.specs ? (
            <>
              {[
                ['GPU', exynos.specs.gpu ? `${exynos.specs.gpu.model} @ ${exynos.specs.gpu.frequency_mhz} MHz` : '—'],
                ['RAM', exynos.specs.memory ? `${exynos.specs.memory.total_mb} MB` : '—'],
                ['Knox', 'Active ✓'],
                ['One UI', oneUiStr || '—'],
              ].map(([k, v]) => (
                <div key={String(k)} className="flex justify-between text-sm">
                  <span className="text-gray-400">{k}</span>
                  <span className="text-gray-200 font-mono text-xs">{String(v ?? '—')}</span>
                </div>
              ))}
            </>
          ) : (
            <>
              {[
                ['Knox', 'Active ✓'],
                ['One UI', oneUiStr || '—'],
                ['Manufacturer', fp.manufacturer || '—'],
              ].map(([k, v]) => (
                <div key={String(k)} className="flex justify-between text-sm">
                  <span className="text-gray-400">{k}</span>
                  <span className="text-gray-200 font-mono text-xs">{String(v ?? '—')}</span>
                </div>
              ))}
            </>
          )}
        </div>
      </div>
    </div>
  )
}

function ADBConsole({ deviceId, isRunning }: { deviceId: number; isRunning: boolean }) {
  const [input, setInput] = useState('')
  const [history, setHistory] = useState<{ cmd: string; output: string; ts: number }[]>([])
  const [loading, setLoading] = useState(false)

  async function runCmd() {
    if (!input.trim() || !isRunning) return
    const cmd = input.trim()
    setInput('')
    setLoading(true)
    const ts = Date.now()
    try {
      const result = await executeShell(deviceId, cmd)
      setHistory((h) => [...h, { cmd, output: result.output, ts }])
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || String(e)
      setHistory((h) => [...h, { cmd, output: `Error: ${msg}`, ts }])
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex flex-col h-96">
      <div className="flex-1 bg-gray-950 rounded-t-lg p-4 overflow-y-auto font-mono text-xs space-y-3">
        {history.length === 0 && (
          <p className="text-gray-600">Type a command below to run via ADB shell...</p>
        )}
        {history.map((entry) => (
          <div key={entry.ts}>
            <div className="text-blue-400">$ {entry.cmd}</div>
            <div className="text-gray-300 whitespace-pre-wrap mt-0.5">{entry.output || '(no output)'}</div>
          </div>
        ))}
        {loading && <div className="text-gray-500 animate-pulse">Running...</div>}
      </div>
      <div className="flex gap-2 mt-2">
        <div className="relative flex-1">
          <span className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500 font-mono text-sm">$</span>
          <input
            className="input pl-7 font-mono"
            placeholder={isRunning ? 'adb shell command...' : 'Device not running'}
            value={input}
            disabled={!isRunning || loading}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && runCmd()}
          />
        </div>
        <button onClick={runCmd} disabled={!isRunning || loading || !input.trim()} className="btn-primary">
          {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : 'Run'}
        </button>
      </div>
    </div>
  )
}

export default function DeviceDetail() {
  const { id } = useParams<{ id: string }>()
  const deviceId = Number(id)
  const navigate = useNavigate()
  const location = useLocation()
  const queryClient = useQueryClient()
  const [currentStatus, setCurrentStatus] = useState<DeviceStatus | null>(null)

  // Extract tab from URL path
  const getActiveTabFromLocation = (): Tab => {
    const pathMatch = location.pathname.match(/\/devices\/\d+(?:\/(\w+))?$/)
    const tabParam = pathMatch?.[1]
    if (tabParam && TABS.some(t => t.id === tabParam)) {
      return tabParam as Tab
    }
    return 'overview'
  }

  const activeTab = getActiveTabFromLocation()

  const { data: device, isLoading } = useQuery({
    queryKey: ['device', deviceId],
    queryFn: () => getDevice(deviceId),
    refetchInterval: 10_000,
  })

  const { data: fpFull } = useQuery({
    queryKey: ['fingerprint-full', deviceId],
    queryFn: () => getFingerprintFull(deviceId),
    enabled: !!device,
  })

  const liveStatus: DeviceStatus = (currentStatus || device?.status || 'created') as DeviceStatus
  const isRunning = liveStatus === 'running'

  /* JPEG افتراضياً — H.264 يعتمد على screenrecord وقد لا يعمل على كل المحاكيات */
  const [screenStreamMode, setScreenStreamMode] = useState<'jpeg' | 'h264'>('jpeg')
  const jpegWsEnabled = !isRunning || screenStreamMode === 'jpeg'
  const {
    lastMessage,
    isConnected: jpegConnected,
    sendMessage,
    liveScreenshot,
    adbUnavailable,
  } = useWebSocket(deviceId, { enabled: jpegWsEnabled })

  const h264CanvasRef = useRef<HTMLCanvasElement>(null)
  const fallbackToJpeg = useCallback(() => setScreenStreamMode('jpeg'), [])
  const h264 = useDeviceH264(deviceId, {
    enabled: isRunning && screenStreamMode === 'h264',
    canvasRef: h264CanvasRef,
    onGiveUp: fallbackToJpeg,
  })

  const sendControl = screenStreamMode === 'jpeg' ? sendMessage : h264.sendControl
  const controlConnected =
    screenStreamMode === 'jpeg' ? jpegConnected : h264.isConnected

  useEffect(() => {
    if (lastMessage?.type === 'status' && lastMessage.status) {
      setCurrentStatus(lastMessage.status)
      queryClient.invalidateQueries({ queryKey: ['device', deviceId] })
    }
  }, [lastMessage, deviceId, queryClient])

  const startMutation = useMutation({
    mutationFn: () => startDevice(deviceId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['device', deviceId] }),
  })
  const stopMutation = useMutation({
    mutationFn: () => stopDevice(deviceId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['device', deviceId] }),
  })
  const restartMutation = useMutation({
    mutationFn: () => restartDevice(deviceId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['device', deviceId] }),
  })

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="w-8 h-8 animate-spin text-blue-400" />
      </div>
    )
  }

  if (!device) {
    return (
      <div className="p-6 text-center">
        <p className="text-gray-400">Device not found</p>
        <button onClick={() => navigate('/devices')} className="btn-secondary mt-4">
          Back to Devices
        </button>
      </div>
    )
  }

  const isBusy = startMutation.isPending || stopMutation.isPending || restartMutation.isPending

  return (
    <div
      className={clsx(
        'p-6 mx-auto w-full',
        activeTab === 'screen' ? 'max-w-[min(1680px,100vw)]' : 'max-w-6xl'
      )}
    >
      {/* Header */}
      <div className="flex items-start justify-between mb-6">
        <div className="flex items-center gap-3">
          <button onClick={() => navigate('/devices')} className="btn-secondary btn-sm">
            <ArrowLeft className="w-4 h-4" />
          </button>
          <div>
            <div className="flex items-center gap-3">
              <h1 className="text-2xl font-bold text-gray-100">{device.name}</h1>
              <span className={STATUS_BADGE[liveStatus]}>{liveStatus}</span>
              {controlConnected && isRunning && (
                <span className="flex items-center gap-1 text-xs text-green-400">
                  <span className="w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse" />
                  Live
                </span>
              )}
            </div>
            <p className="text-gray-400 text-sm mt-1 font-mono">{device.adb_serial || 'Not connected'}</p>
          </div>
        </div>

        {/* Action buttons */}
        <div className="flex gap-2">
          {!isRunning ? (
            <button
              onClick={() => startMutation.mutate()}
              disabled={isBusy || liveStatus === 'booting'}
              className="btn-success"
            >
              {startMutation.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
              Start
            </button>
          ) : (
            <>
              <button
                onClick={() => stopMutation.mutate()}
                disabled={isBusy}
                className="btn-secondary"
              >
                {stopMutation.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Square className="w-4 h-4" />}
                Stop
              </button>
              <button
                onClick={() => restartMutation.mutate()}
                disabled={isBusy}
                className="btn-secondary"
              >
                {restartMutation.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <RotateCcw className="w-4 h-4" />}
                Restart
              </button>
            </>
          )}
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 mb-6 flex-wrap">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            onClick={() => tab.id === 'overview'
              ? navigate(`/devices/${deviceId}`)
              : navigate(`/devices/${deviceId}/${tab.id}`)}
            className={clsx(
              'flex items-center gap-2',
              activeTab === tab.id ? 'tab-btn-active' : 'tab-btn-inactive'
            )}
          >
            {tab.icon}
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab Content */}
      {activeTab === 'overview' && (
        <div className="space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="card space-y-3">
              <h3 className="font-semibold text-gray-200 mb-3">Device Info</h3>
              {[
                ['ID', device.id],
                ['Status', liveStatus],
                ['AVD Name', device.avd_name || '—'],
                ['ADB Serial', device.adb_serial || '—'],
                ['ADB Port', device.adb_port ? `:${device.adb_port}` : '—'],
                ['Console Port', device.console_port ? `:${device.console_port}` : '—'],
                ['PID', device.pid || '—'],
              ].map(([k, v]) => (
                <div key={String(k)} className="flex justify-between text-sm">
                  <span className="text-gray-400">{k}</span>
                  <span className="text-gray-200 font-mono">{String(v)}</span>
                </div>
              ))}
            </div>
            <div className="card space-y-3">
              <h3 className="font-semibold text-gray-200 mb-3">Hardware</h3>
              {[
                ['API Level', `Android API ${device.api_level}`],
                ['Architecture', device.arch],
                ['RAM', `${device.ram_mb} MB`],
                ['CPU Cores', device.cpu_cores],
                ['Owner ID', device.owner_id],
                ['Created', new Date(device.created_at).toLocaleString()],
                ['Updated', new Date(device.updated_at).toLocaleString()],
              ].map(([k, v]) => (
                <div key={String(k)} className="flex justify-between text-sm">
                  <span className="text-gray-400">{k}</span>
                  <span className="text-gray-200 font-mono">{String(v)}</span>
                </div>
              ))}
            </div>
          </div>

          {/* Samsung card — only shown for Samsung devices */}
          {fpFull?.device_model?.startsWith('SM-') && (
            <SamsungCard fp={fpFull} />
          )}
        </div>
      )}

      {activeTab === 'screen' && (
        <div className="card">
          <h3 className="font-semibold text-gray-200 mb-1">شاشة حية — تحكم مثل المحاكي</h3>
          <p className="text-xs text-gray-500 mb-4">
            JPEG عبر لقطات ADB، أو H.264 عبر <code className="text-gray-400">screenrecord</code> و WebCodecs
            (تأخير أقل). يتطلب متصفحاً يدعم VideoDecoder.
          </p>
          <DeviceScreen
            deviceId={deviceId}
            serial={device.adb_serial}
            isRunning={isRunning}
            sendControl={sendControl}
            controlConnected={controlConnected}
            jpegConnected={jpegConnected}
            liveScreenshot={liveScreenshot}
            adbUnavailable={screenStreamMode === 'jpeg' ? adbUnavailable : null}
            screenStreamMode={screenStreamMode}
            onScreenStreamModeChange={setScreenStreamMode}
            h264CanvasRef={h264CanvasRef}
            h264StreamWidth={h264.streamWidth}
            h264StreamHeight={h264.streamHeight}
            h264DeviceWidth={h264.deviceWidth}
            h264DeviceHeight={h264.deviceHeight}
            h264Error={h264.error}
            h264Status={h264.status}
          />
        </div>
      )}

      {activeTab === 'fingerprint' && (
        <FingerprintEditor deviceId={deviceId} isRunning={isRunning} />
      )}

      {activeTab === 'apps' && (
        <APKInstaller deviceId={deviceId} isRunning={isRunning} />
      )}

      {activeTab === 'proxy' && (
        <ProxyConfig deviceId={deviceId} isRunning={isRunning} />
      )}

      {activeTab === 'console' && (
        <div className="card">
          <h3 className="font-semibold text-gray-200 mb-4">ADB Shell Console</h3>
          {!isRunning && (
            <div className="bg-yellow-900/20 border border-yellow-800 rounded-lg p-3 text-yellow-400 text-sm mb-4">
              Device must be running to use the console
            </div>
          )}
          <ADBConsole deviceId={deviceId} isRunning={isRunning} />
        </div>
      )}

      {activeTab === 'frida' && (
        <FridaManager deviceId={deviceId} isRunning={isRunning} />
      )}

      {activeTab === 'logs' && (
        <LogsViewer deviceId={deviceId} isRunning={isRunning} />
      )}
    </div>
  )
}
