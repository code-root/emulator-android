import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Play, Square, Eye, Loader2, Cpu } from 'lucide-react'
import { startDevice, stopDevice, getScreenshot } from '../api/client'
import type { Device, DeviceStatus } from '../types'
import clsx from 'clsx'
import { formatDistanceToNow } from 'date-fns'

const STATUS_CLASSES: Record<DeviceStatus, { badge: string; dot: string }> = {
  created:  { badge: 'badge-created',  dot: 'bg-blue-400' },
  booting:  { badge: 'badge-booting',  dot: 'bg-yellow-400 animate-pulse' },
  running:  { badge: 'badge-running',  dot: 'bg-green-400' },
  stopped:  { badge: 'badge-stopped',  dot: 'bg-gray-500' },
  error:    { badge: 'badge-error',    dot: 'bg-red-400' },
}

interface DeviceCardProps {
  device: Device
  onRefresh: () => void
}

export default function DeviceCard({ device, onRefresh }: DeviceCardProps) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const { data: shotBlob } = useQuery({
    queryKey: ['screenshot-thumb', device.id],
    queryFn: () => getScreenshot(device.id),
    enabled: device.status === 'running',
    staleTime: 20_000,
    refetchInterval: 25_000,
  })

  const [thumbUrl, setThumbUrl] = useState<string | null>(null)
  useEffect(() => {
    if (!shotBlob) {
      setThumbUrl(null)
      return
    }
    const u = URL.createObjectURL(shotBlob)
    setThumbUrl(u)
    return () => URL.revokeObjectURL(u)
  }, [shotBlob])

  const startMutation = useMutation({
    mutationFn: () => startDevice(device.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['devices'] })
      onRefresh()
    },
  })

  const stopMutation = useMutation({
    mutationFn: () => stopDevice(device.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['devices'] })
      onRefresh()
    },
  })

  const statusCls = STATUS_CLASSES[device.status] || STATUS_CLASSES.stopped
  const isRunning = device.status === 'running'
  const isBooting = device.status === 'booting'
  const isBusy = startMutation.isPending || stopMutation.isPending

  return (
    <div className="card hover:border-gray-700 transition-colors group">
      {/* Header */}
      <div className="flex items-start justify-between mb-4">
        <div className="flex items-center gap-2 min-w-0">
          <div className={clsx('w-2.5 h-2.5 rounded-full shrink-0', statusCls.dot)} />
          <h3 className="font-semibold text-gray-100 truncate">{device.name}</h3>
        </div>
        <span className={statusCls.badge}>{device.status}</span>
      </div>

      {/* Info grid */}
      <div className="grid grid-cols-2 gap-x-4 gap-y-2 text-xs mb-4">
        <div>
          <span className="text-gray-500">ADB Port</span>
          <p className="text-gray-300 font-mono">{device.adb_port ? `:${device.adb_port}` : '—'}</p>
        </div>
        <div>
          <span className="text-gray-500">API Level</span>
          <p className="text-gray-300">API {device.api_level}</p>
        </div>
        <div>
          <span className="text-gray-500">RAM</span>
          <p className="text-gray-300">{device.ram_mb} MB</p>
        </div>
        <div>
          <span className="text-gray-500">CPU</span>
          <p className="text-gray-300">{device.cpu_cores} cores</p>
        </div>
      </div>

      {device.adb_serial && (
        <div className="text-xs font-mono text-gray-500 mb-4 truncate">{device.adb_serial}</div>
      )}

      <div className="text-xs text-gray-600 mb-4">
        Created {formatDistanceToNow(new Date(device.created_at))} ago
      </div>

      {thumbUrl && (
        <div className="mb-4 rounded-lg overflow-hidden border border-gray-800 bg-black aspect-video flex items-center justify-center">
          <img src={thumbUrl} alt="" className="max-h-28 object-contain w-full" />
        </div>
      )}

      {/* Actions */}
      <div className="flex gap-2">
        <button
          onClick={() => navigate(`/devices/${device.id}`)}
          className="btn-secondary btn-sm flex-1 justify-center"
        >
          <Eye className="w-3.5 h-3.5" />
          View
        </button>

        {!isRunning && !isBooting ? (
          <button
            onClick={() => startMutation.mutate()}
            disabled={isBusy}
            className="btn-success btn-sm flex-1 justify-center"
          >
            {startMutation.isPending
              ? <Loader2 className="w-3.5 h-3.5 animate-spin" />
              : <Play className="w-3.5 h-3.5" />}
            Start
          </button>
        ) : isBooting ? (
          <button disabled className="btn-secondary btn-sm flex-1 justify-center opacity-70">
            <Loader2 className="w-3.5 h-3.5 animate-spin" />
            Booting
          </button>
        ) : (
          <button
            onClick={() => stopMutation.mutate()}
            disabled={isBusy}
            className="btn-secondary btn-sm flex-1 justify-center"
          >
            {stopMutation.isPending
              ? <Loader2 className="w-3.5 h-3.5 animate-spin" />
              : <Square className="w-3.5 h-3.5" />}
            Stop
          </button>
        )}
      </div>
    </div>
  )
}
