import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Play, Square, RotateCcw, ArrowLeft, Loader2,
  Monitor, Fingerprint, AppWindow, Shield, Terminal, ScrollText, Info
} from 'lucide-react'
import { getDevice, startDevice, stopDevice, restartDevice, executeShell } from '../api/client'
import { useWebSocket } from '../hooks/useWebSocket'
import DeviceScreen from '../components/DeviceScreen'
import FingerprintEditor from '../components/FingerprintEditor'
import APKInstaller from '../components/APKInstaller'
import ProxyConfig from '../components/ProxyConfig'
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

type Tab = 'overview' | 'screen' | 'fingerprint' | 'apps' | 'proxy' | 'console' | 'logs'

const TABS: { id: Tab; label: string; icon: React.ReactNode }[] = [
  { id: 'overview', label: 'Overview', icon: <Info className="w-4 h-4" /> },
  { id: 'screen', label: 'Screen', icon: <Monitor className="w-4 h-4" /> },
  { id: 'fingerprint', label: 'Fingerprint', icon: <Fingerprint className="w-4 h-4" /> },
  { id: 'apps', label: 'Apps', icon: <AppWindow className="w-4 h-4" /> },
  { id: 'proxy', label: 'Proxy', icon: <Shield className="w-4 h-4" /> },
  { id: 'console', label: 'Console', icon: <Terminal className="w-4 h-4" /> },
  { id: 'logs', label: 'Logs', icon: <ScrollText className="w-4 h-4" /> },
]

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
  const queryClient = useQueryClient()
  const [activeTab, setActiveTab] = useState<Tab>('overview')
  const [currentStatus, setCurrentStatus] = useState<DeviceStatus | null>(null)

  const { data: device, isLoading } = useQuery({
    queryKey: ['device', deviceId],
    queryFn: () => getDevice(deviceId),
    refetchInterval: 10_000,
  })

  const { lastMessage, isConnected, sendMessage, liveScreenshot } = useWebSocket(deviceId)

  useEffect(() => {
    if (lastMessage?.type === 'status' && lastMessage.status) {
      setCurrentStatus(lastMessage.status)
      queryClient.invalidateQueries({ queryKey: ['device', deviceId] })
    }
  }, [lastMessage, deviceId, queryClient])

  const liveStatus: DeviceStatus = (currentStatus || device?.status || 'created') as DeviceStatus

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

  const isRunning = liveStatus === 'running'
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
              {isConnected && (
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
            onClick={() => setActiveTab(tab.id)}
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
      )}

      {activeTab === 'screen' && (
        <div className="card">
          <h3 className="font-semibold text-gray-200 mb-1">شاشة حية — تحكم مثل المحاكي</h3>
          <p className="text-xs text-gray-500 mb-4">
            بث سريع عبر السيرفر (ADB). للأداء الأقصى لاحقاً يمكن ربط scrcpy مباشرة.
          </p>
          <DeviceScreen
            deviceId={deviceId}
            serial={device.adb_serial}
            isRunning={isRunning}
            sendMessage={sendMessage}
            isConnected={isConnected}
            liveScreenshot={liveScreenshot}
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

      {activeTab === 'logs' && (
        <LogsViewer deviceId={deviceId} isRunning={isRunning} />
      )}
    </div>
  )
}
