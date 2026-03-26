import { useQuery } from '@tanstack/react-query'
import { Activity, Cpu, AlertTriangle, Square, RefreshCw } from 'lucide-react'
import { getDevices, getRecentOperationLogs } from '../api/client'
import DeviceCard from '../components/DeviceCard'
import { formatDistanceToNow } from 'date-fns'
import type { Device, OperationLog } from '../types'

interface StatCardProps {
  label: string
  value: number
  icon: React.ReactNode
  color: string
}

function StatCard({ label, value, icon, color }: StatCardProps) {
  return (
    <div className="card flex items-center gap-4">
      <div className={`p-3 rounded-xl ${color}`}>{icon}</div>
      <div>
        <p className="text-3xl font-bold text-gray-100">{value}</p>
        <p className="text-sm text-gray-400 mt-0.5">{label}</p>
      </div>
    </div>
  )
}

export default function Dashboard() {
  const { data: devices = [], isLoading, refetch, dataUpdatedAt } = useQuery({
    queryKey: ['devices'],
    queryFn: getDevices,
    refetchInterval: 30_000,
  })

  const { data: recentLogs = [] } = useQuery({
    queryKey: ['operation-logs-recent'],
    queryFn: () => getRecentOperationLogs(40),
    refetchInterval: 30_000,
  })

  const stats = {
    total: devices.length,
    running: devices.filter((d) => d.status === 'running').length,
    stopped: devices.filter((d) => d.status === 'stopped').length,
    error: devices.filter((d) => d.status === 'error').length,
  }

  return (
    <div className="p-6 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-bold text-gray-100">Dashboard</h1>
          <p className="text-gray-400 text-sm mt-1">
            {dataUpdatedAt
              ? `Updated ${formatDistanceToNow(new Date(dataUpdatedAt))} ago`
              : 'Loading...'}
          </p>
        </div>
        <button
          onClick={() => refetch()}
          disabled={isLoading}
          className="btn-secondary"
        >
          <RefreshCw className={`w-4 h-4 ${isLoading ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        <StatCard
          label="Total Devices"
          value={stats.total}
          icon={<Cpu className="w-5 h-5 text-blue-400" />}
          color="bg-blue-900/40"
        />
        <StatCard
          label="Running"
          value={stats.running}
          icon={<Activity className="w-5 h-5 text-green-400" />}
          color="bg-green-900/40"
        />
        <StatCard
          label="Stopped"
          value={stats.stopped}
          icon={<Square className="w-5 h-5 text-gray-400" />}
          color="bg-gray-800"
        />
        <StatCard
          label="Errors"
          value={stats.error}
          icon={<AlertTriangle className="w-5 h-5 text-red-400" />}
          color="bg-red-900/40"
        />
      </div>

      {/* Device Grid */}
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-lg font-semibold text-gray-200">All Devices</h2>
        <span className="text-sm text-gray-500">{devices.length} devices</span>
      </div>

      {isLoading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="card animate-pulse h-40" />
          ))}
        </div>
      ) : devices.length === 0 ? (
        <div className="card text-center py-16">
          <Cpu className="w-12 h-12 text-gray-600 mx-auto mb-4" />
          <p className="text-gray-400 text-lg">No devices yet</p>
          <p className="text-gray-600 text-sm mt-2">Go to Devices to create your first emulator</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {devices.map((device: Device) => (
            <DeviceCard key={device.id} device={device} onRefresh={() => refetch()} />
          ))}
        </div>
      )}

      <div className="mt-10">
        <h2 className="text-lg font-semibold text-gray-200 mb-4">Recent operations</h2>
        <div className="card overflow-x-auto p-0">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-800 text-left">
                <th className="text-gray-400 font-medium px-4 py-3">Time</th>
                <th className="text-gray-400 font-medium px-4 py-3">Device</th>
                <th className="text-gray-400 font-medium px-4 py-3">Action</th>
                <th className="text-gray-400 font-medium px-4 py-3">Status</th>
                <th className="text-gray-400 font-medium px-4 py-3">Detail</th>
              </tr>
            </thead>
            <tbody>
              {recentLogs.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-4 py-8 text-center text-gray-500">
                    No operation logs yet
                  </td>
                </tr>
              ) : (
                recentLogs.map((log: OperationLog) => (
                  <tr key={log.id} className="border-b border-gray-800/50 hover:bg-gray-800/20">
                    <td className="px-4 py-2 text-gray-500 whitespace-nowrap text-xs">
                      {formatDistanceToNow(new Date(log.created_at))} ago
                    </td>
                    <td className="px-4 py-2 text-gray-300 font-mono text-xs">{log.device_id ?? '—'}</td>
                    <td className="px-4 py-2 text-gray-200">{log.action}</td>
                    <td className="px-4 py-2">
                      <span
                        className={
                          log.status === 'success'
                            ? 'text-green-400'
                            : log.status === 'failure'
                              ? 'text-red-400'
                              : 'text-yellow-400'
                        }
                      >
                        {log.status}
                      </span>
                    </td>
                    <td className="px-4 py-2 text-gray-500 text-xs max-w-md truncate">{log.detail ?? '—'}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
