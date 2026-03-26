import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus, Search, Trash2, Play, Square, Eye, Loader2, Cpu } from 'lucide-react'
import { getDevices, createDevice, startDevice, stopDevice, deleteDevice, getDevicePresets } from '../api/client'
import type { Device, DeviceCreateForm, DeviceStatus } from '../types'
import { formatDistanceToNow } from 'date-fns'
import clsx from 'clsx'

const STATUS_BADGE: Record<DeviceStatus, string> = {
  created: 'badge-created',
  booting: 'badge-booting',
  running: 'badge-running',
  stopped: 'badge-stopped',
  error: 'badge-error',
}

const STATUS_DOT: Record<DeviceStatus, string> = {
  created: 'bg-blue-400',
  booting: 'bg-yellow-400 animate-pulse',
  running: 'bg-green-400',
  stopped: 'bg-gray-500',
  error: 'bg-red-400',
}

function CreateDeviceModal({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient()
  const [form, setForm] = useState<DeviceCreateForm>({
    name: '',
    ram_mb: 2048,
    cpu_cores: 2,
    api_level: 31,
    arch: 'x86_64',
    preset: null,
  })

  const { data: presets = [] } = useQuery({
    queryKey: ['device-presets'],
    queryFn: getDevicePresets,
  })

  const mutation = useMutation({
    mutationFn: () => createDevice(form),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['devices'] })
      onClose()
    },
  })

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="card w-full max-w-md mx-4">
        <h2 className="text-lg font-semibold mb-4">Create New Device</h2>

        {mutation.error && (
          <div className="text-red-400 text-sm bg-red-900/20 border border-red-800 rounded-lg p-3 mb-4">
            {String((mutation.error as { response?: { data?: { detail?: string } } })?.response?.data?.detail || mutation.error)}
          </div>
        )}

        <div className="space-y-4">
          <div>
            <label className="label">Preset (اختياري — مثال Samsung G996B + Android 15)</label>
            <select
              className="input"
              value={form.preset ?? ''}
              onChange={(e) =>
                setForm({
                  ...form,
                  preset: e.target.value || null,
                })
              }
            >
              <option value="">بدون — استخدام الإعدادات اليدوية أدناه</option>
              {presets.map((p) => (
                <option key={p.key} value={p.key}>
                  {p.label} (API {p.api_level}, {p.arch})
                </option>
              ))}
            </select>
            <p className="text-xs text-gray-500 mt-1">
              عند اختيار preset يُضبط مستوى API والبصمة تلقائياً (يتطلب تثبيت system-images;android-35 عبر sdkmanager).
            </p>
          </div>
          <div>
            <label className="label">Device Name *</label>
            <input
              className="input"
              placeholder="My Android Device"
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
            />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="label">RAM (MB)</label>
              <select
                className="input"
                value={form.ram_mb}
                onChange={(e) => setForm({ ...form, ram_mb: Number(e.target.value) })}
              >
                {[1024, 2048, 4096, 8192].map((v) => (
                  <option key={v} value={v}>{v} MB</option>
                ))}
              </select>
            </div>
            <div>
              <label className="label">CPU Cores</label>
              <select
                className="input"
                value={form.cpu_cores}
                onChange={(e) => setForm({ ...form, cpu_cores: Number(e.target.value) })}
              >
                {[1, 2, 4, 8].map((v) => (
                  <option key={v} value={v}>{v} core{v > 1 ? 's' : ''}</option>
                ))}
              </select>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="label">API Level</label>
              <select
                className="input"
                value={form.api_level}
                disabled={!!form.preset}
                onChange={(e) => setForm({ ...form, api_level: Number(e.target.value) })}
              >
                {[28, 29, 30, 31, 32, 33, 34, 35].map((v) => (
                  <option key={v} value={v}>API {v}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="label">Architecture</label>
              <select
                className="input"
                value={form.arch}
                disabled={!!form.preset}
                onChange={(e) => setForm({ ...form, arch: e.target.value })}
              >
                <option value="x86_64">x86_64</option>
                <option value="arm64-v8a">arm64-v8a</option>
                <option value="x86">x86</option>
              </select>
            </div>
          </div>
        </div>

        <div className="flex gap-3 mt-6">
          <button onClick={onClose} className="btn-secondary flex-1 justify-center">Cancel</button>
          <button
            onClick={() => mutation.mutate()}
            disabled={!form.name || mutation.isPending}
            className="btn-primary flex-1 justify-center"
          >
            {mutation.isPending && <Loader2 className="w-4 h-4 animate-spin" />}
            Create Device
          </button>
        </div>
      </div>
    </div>
  )
}

export default function Devices() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [showCreate, setShowCreate] = useState(false)
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState<DeviceStatus | 'all'>('all')
  const [loadingDevices, setLoadingDevices] = useState<Record<number, string>>({})

  const { data: devices = [], isLoading } = useQuery({
    queryKey: ['devices'],
    queryFn: getDevices,
    refetchInterval: 15_000,
  })

  const filtered = devices.filter((d: Device) => {
    const matchSearch = d.name.toLowerCase().includes(search.toLowerCase())
    const matchStatus = statusFilter === 'all' || d.status === statusFilter
    return matchSearch && matchStatus
  })

  async function handleStart(device: Device) {
    setLoadingDevices((prev) => ({ ...prev, [device.id]: 'starting' }))
    try {
      await startDevice(device.id)
      queryClient.invalidateQueries({ queryKey: ['devices'] })
    } finally {
      setLoadingDevices((prev) => {
        const n = { ...prev }; delete n[device.id]; return n
      })
    }
  }

  async function handleStop(device: Device) {
    setLoadingDevices((prev) => ({ ...prev, [device.id]: 'stopping' }))
    try {
      await stopDevice(device.id)
      queryClient.invalidateQueries({ queryKey: ['devices'] })
    } finally {
      setLoadingDevices((prev) => {
        const n = { ...prev }; delete n[device.id]; return n
      })
    }
  }

  async function handleDelete(device: Device) {
    if (!confirm(`Delete device "${device.name}"? This action cannot be undone.`)) return
    try {
      await deleteDevice(device.id)
      queryClient.invalidateQueries({ queryKey: ['devices'] })
    } catch (e) {
      alert('Delete failed: ' + String(e))
    }
  }

  const statuses: Array<DeviceStatus | 'all'> = ['all', 'running', 'booting', 'stopped', 'error', 'created']

  return (
    <div className="p-6 max-w-7xl mx-auto">
      {showCreate && <CreateDeviceModal onClose={() => setShowCreate(false)} />}

      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-100">Devices</h1>
          <p className="text-gray-400 text-sm mt-1">{devices.length} total devices</p>
        </div>
        <button onClick={() => setShowCreate(true)} className="btn-primary">
          <Plus className="w-4 h-4" />
          New Device
        </button>
      </div>

      {/* Filters */}
      <div className="flex flex-col sm:flex-row gap-3 mb-6">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500" />
          <input
            className="input pl-9"
            placeholder="Search devices..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <div className="flex gap-2 flex-wrap">
          {statuses.map((s) => (
            <button
              key={s}
              onClick={() => setStatusFilter(s)}
              className={clsx(
                'px-3 py-1.5 rounded-lg text-xs font-medium transition-colors capitalize',
                statusFilter === s
                  ? 'bg-blue-600 text-white'
                  : 'bg-gray-800 text-gray-400 hover:text-gray-200'
              )}
            >
              {s}
            </button>
          ))}
        </div>
      </div>

      {/* Table */}
      {isLoading ? (
        <div className="card flex items-center justify-center h-40">
          <Loader2 className="w-6 h-6 animate-spin text-blue-400" />
        </div>
      ) : filtered.length === 0 ? (
        <div className="card text-center py-16">
          <Cpu className="w-12 h-12 text-gray-600 mx-auto mb-4" />
          <p className="text-gray-400">No devices found</p>
        </div>
      ) : (
        <div className="card overflow-x-auto p-0">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-800">
                <th className="text-left text-gray-400 font-medium px-5 py-3">Name</th>
                <th className="text-left text-gray-400 font-medium px-5 py-3">Status</th>
                <th className="text-left text-gray-400 font-medium px-5 py-3">ADB Port</th>
                <th className="text-left text-gray-400 font-medium px-5 py-3">API Level</th>
                <th className="text-left text-gray-400 font-medium px-5 py-3">RAM</th>
                <th className="text-left text-gray-400 font-medium px-5 py-3">Created</th>
                <th className="text-left text-gray-400 font-medium px-5 py-3">Actions</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((device: Device) => {
                const isLoading = !!loadingDevices[device.id]
                return (
                  <tr
                    key={device.id}
                    className="border-b border-gray-800/50 hover:bg-gray-800/30 transition-colors"
                  >
                    <td className="px-5 py-3">
                      <div className="flex items-center gap-2">
                        <div className={clsx('w-2 h-2 rounded-full', STATUS_DOT[device.status])} />
                        <span className="font-medium text-gray-100">{device.name}</span>
                      </div>
                      {device.adb_serial && (
                        <span className="text-xs text-gray-500 font-mono ml-4">{device.adb_serial}</span>
                      )}
                    </td>
                    <td className="px-5 py-3">
                      <span className={STATUS_BADGE[device.status]}>{device.status}</span>
                    </td>
                    <td className="px-5 py-3 font-mono text-gray-300">
                      {device.adb_port ? `:${device.adb_port}` : '—'}
                    </td>
                    <td className="px-5 py-3 text-gray-300">API {device.api_level}</td>
                    <td className="px-5 py-3 text-gray-300">{device.ram_mb} MB</td>
                    <td className="px-5 py-3 text-gray-400 text-xs">
                      {formatDistanceToNow(new Date(device.created_at))} ago
                    </td>
                    <td className="px-5 py-3">
                      <div className="flex items-center gap-1">
                        <button
                          onClick={() => navigate(`/devices/${device.id}`)}
                          className="btn-secondary btn-sm"
                        >
                          <Eye className="w-3.5 h-3.5" />
                        </button>
                        {device.status !== 'running' && device.status !== 'booting' ? (
                          <button
                            onClick={() => handleStart(device)}
                            disabled={isLoading}
                            className="btn-success btn-sm"
                          >
                            {isLoading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Play className="w-3.5 h-3.5" />}
                          </button>
                        ) : (
                          <button
                            onClick={() => handleStop(device)}
                            disabled={isLoading}
                            className="btn-secondary btn-sm"
                          >
                            {isLoading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Square className="w-3.5 h-3.5" />}
                          </button>
                        )}
                        <button
                          onClick={() => handleDelete(device)}
                          className="btn-danger btn-sm"
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
