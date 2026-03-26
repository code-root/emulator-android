import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Shield, Play, Square, RefreshCw, Loader2 } from 'lucide-react'
import {
  getProxy,
  setProxy,
  startMitmProxy,
  stopMitmProxy,
  getProxyTraffic,
} from '../api/client'
import type { ProxyConfig as ProxyConfigType } from '../types'
import clsx from 'clsx'

interface Props {
  deviceId: number
  isRunning: boolean
}

export default function ProxyConfig({ deviceId, isRunning }: Props) {
  const queryClient = useQueryClient()
  const [form, setForm] = useState<Partial<ProxyConfigType>>({})

  const { data: proxy, isLoading } = useQuery({
    queryKey: ['proxy', deviceId],
    queryFn: () => getProxy(deviceId),
  })

  useEffect(() => {
    if (proxy) setForm(proxy)
  }, [proxy])

  const trafficQuery = useQuery({
    queryKey: ['proxy-traffic', deviceId],
    queryFn: () => getProxyTraffic(deviceId, 80),
    enabled: !!proxy?.mitm_active,
    refetchInterval: 5_000,
  })

  const saveMutation = useMutation({
    mutationFn: () =>
      setProxy(deviceId, {
        enabled: !!form.enabled,
        proxy_type: form.proxy_type ?? 'http',
        host: form.host ?? null,
        port: form.port ?? null,
        username: form.username ?? null,
        password: form.password ?? null,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['proxy', deviceId] })
    },
  })

  const startMitm = useMutation({
    mutationFn: () => startMitmProxy(deviceId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['proxy', deviceId] })
      queryClient.invalidateQueries({ queryKey: ['proxy-traffic', deviceId] })
    },
  })

  const stopMitm = useMutation({
    mutationFn: () => stopMitmProxy(deviceId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['proxy', deviceId] })
    },
  })

  if (isLoading || !proxy) {
    return (
      <div className="card flex justify-center py-16">
        <Loader2 className="w-8 h-8 animate-spin text-blue-400" />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="card space-y-4">
        <h3 className="font-semibold text-gray-200 flex items-center gap-2">
          <Shield className="w-4 h-4" />
          HTTP proxy (global settings)
        </h3>

        <label className="flex items-center gap-2 text-sm text-gray-300 cursor-pointer">
          <input
            type="checkbox"
            checked={!!form.enabled}
            onChange={(e) => setForm((f) => ({ ...f, enabled: e.target.checked }))}
            disabled={!isRunning}
          />
          Enable proxy on device
        </label>

        <div>
          <label className="label">Type</label>
          <select
            className="input"
            value={form.proxy_type ?? 'http'}
            onChange={(e) =>
              setForm((f) => ({ ...f, proxy_type: e.target.value as ProxyConfigType['proxy_type'] }))
            }
          >
            <option value="http">HTTP</option>
            <option value="socks5">SOCKS5</option>
          </select>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div>
            <label className="label">Host</label>
            <input className="input font-mono" value={form.host ?? ''} onChange={(e) => setForm((f) => ({ ...f, host: e.target.value }))} />
          </div>
          <div>
            <label className="label">Port</label>
            <input
              type="number"
              className="input"
              value={form.port ?? ''}
              onChange={(e) => setForm((f) => ({ ...f, port: e.target.value ? Number(e.target.value) : null }))}
            />
          </div>
          <div>
            <label className="label">Username</label>
            <input className="input" value={form.username ?? ''} onChange={(e) => setForm((f) => ({ ...f, username: e.target.value }))} />
          </div>
          <div>
            <label className="label">Password</label>
            <input
              type="password"
              className="input"
              value={form.password ?? ''}
              onChange={(e) => setForm((f) => ({ ...f, password: e.target.value }))}
            />
          </div>
        </div>

        <button
          type="button"
          className="btn-primary"
          disabled={saveMutation.isPending || !isRunning}
          onClick={() => saveMutation.mutate()}
        >
          {saveMutation.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : null}
          Save & push to device
        </button>
      </div>

      <div className="card space-y-4">
        <h3 className="font-semibold text-gray-200">mitmproxy (per device)</h3>
        <p className="text-sm text-gray-500">
          Starts mitmdump on the farm host and points the device HTTP proxy at it. Emulator must reach host networking; in Docker you may need
          host.docker.internal or a bridge IP instead of 127.0.0.1.
        </p>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            className="btn-success btn-sm"
            disabled={!isRunning || startMitm.isPending || proxy.mitm_active}
            onClick={() => startMitm.mutate()}
          >
            {startMitm.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
            Start mitmproxy
          </button>
          <button
            type="button"
            className="btn-secondary btn-sm"
            disabled={!proxy.mitm_active || stopMitm.isPending}
            onClick={() => stopMitm.mutate()}
          >
            {stopMitm.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Square className="w-4 h-4" />}
            Stop mitmproxy
          </button>
        </div>
        <div className={clsx('text-xs font-mono rounded-lg p-3', proxy.mitm_active ? 'bg-green-900/20 text-green-300' : 'bg-gray-800 text-gray-500')}>
          Status: {proxy.mitm_active ? `listening on port ${proxy.mitm_port ?? '?'}` : 'inactive'}
        </div>
      </div>

      <div className="card space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="font-semibold text-gray-200">Traffic log preview</h3>
          <button type="button" className="btn-secondary btn-sm" onClick={() => trafficQuery.refetch()}>
            <RefreshCw className={clsx('w-3.5 h-3.5', trafficQuery.isFetching && 'animate-spin')} />
          </button>
        </div>
        <pre className="text-xs font-mono bg-gray-950 border border-gray-800 rounded-lg p-3 max-h-64 overflow-auto text-gray-400 whitespace-pre-wrap">
          {(trafficQuery.data?.entries ?? []).join('\n') || 'No traffic lines yet (mitmproxy writes console output to a log file).'}
        </pre>
      </div>
    </div>
  )
}
