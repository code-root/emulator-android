import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Shuffle, Save, Send, Loader2, AlertCircle } from 'lucide-react'
import {
  getFingerprint,
  updateFingerprint,
  applyFingerprint,
  randomizeFingerprint,
  getDeviceProfiles,
} from '../api/client'
import type { DeviceFingerprint } from '../types'
import clsx from 'clsx'

const IMEI_RE = /^\d{15}$/
const ANDROID_ID_RE = /^[0-9a-fA-F]{16}$/
const MAC_RE = /^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$/

interface Props {
  deviceId: number
  isRunning: boolean
}

function validate(fp: Partial<DeviceFingerprint>): string | null {
  if (fp.imei && !IMEI_RE.test(fp.imei)) return 'IMEI must be exactly 15 digits'
  if (fp.android_id && !ANDROID_ID_RE.test(fp.android_id)) return 'Android ID must be 16 hex characters'
  if (fp.mac_address && !MAC_RE.test(fp.mac_address)) return 'MAC must be AA:BB:CC:DD:EE:FF format'
  if (fp.latitude != null && (fp.latitude < -90 || fp.latitude > 90)) return 'Latitude must be between -90 and 90'
  if (fp.longitude != null && (fp.longitude < -180 || fp.longitude > 180)) return 'Longitude must be between -180 and 180'
  return null
}

export default function FingerprintEditor({ deviceId, isRunning }: Props) {
  const queryClient = useQueryClient()
  const [form, setForm] = useState<Partial<DeviceFingerprint>>({})
  const [error, setError] = useState<string | null>(null)
  const [statusMsg, setStatusMsg] = useState<string | null>(null)

  const { data: fp, isLoading } = useQuery({
    queryKey: ['fingerprint', deviceId],
    queryFn: () => getFingerprint(deviceId),
  })

  const { data: profiles = [] } = useQuery({
    queryKey: ['device-profiles'],
    queryFn: getDeviceProfiles,
  })

  useEffect(() => {
    if (fp) setForm({ ...fp })
  }, [fp])

  const profileOptions = useMemo(
    () => profiles.map((p) => p.device_model).sort(),
    [profiles]
  )

  function applyProfileModel(model: string) {
    const p = profiles.find((x) => x.device_model === model)
    if (!p) return
    setForm((prev) => ({
      ...prev,
      device_model: p.device_model,
      manufacturer: p.manufacturer,
      brand: p.brand,
      device_codename: p.device_codename,
      build_fingerprint: p.build_fingerprint,
      sdk_version: p.sdk_version,
      android_version: p.android_version,
    }))
  }

  const saveMutation = useMutation({
    mutationFn: () => {
      const err = validate(form)
      if (err) throw new Error(err)
      const { id: _i, device_id: _d, updated_at: _u, ...rest } = { ...fp, ...form } as DeviceFingerprint
      return updateFingerprint(deviceId, rest)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['fingerprint', deviceId] })
      setStatusMsg('Saved successfully')
      setError(null)
    },
    onError: (e: Error) => {
      setError(e.message)
      setStatusMsg(null)
    },
  })

  const randomMutation = useMutation({
    mutationFn: (apply: boolean) => randomizeFingerprint(deviceId, apply),
    onSuccess: (data) => {
      setForm({ ...data })
      queryClient.invalidateQueries({ queryKey: ['fingerprint', deviceId] })
      setStatusMsg('Randomized')
      setError(null)
    },
    onError: (e: Error) => {
      setError(String(e))
      setStatusMsg(null)
    },
  })

  const applyMutation = useMutation({
    mutationFn: () => applyFingerprint(deviceId),
    onSuccess: (data) => {
      const n = data.report?.applied?.length ?? 0
      const f = data.report?.failed?.length ?? 0
      const extra = data.note ? ` ${data.note}` : ''
      if (data.samsung_extended_spoof) {
        setStatusMsg(
          `Samsung extended spoof: ${n} props accepted, ${f} rejected (normal on AVD).${extra}`
        )
      } else {
        setStatusMsg(`Fingerprint apply: ${n} ok, ${f} failed (userdebug/root helps).`)
      }
      setError(null)
    },
    onError: (e: Error) => {
      setError(String(e))
      setStatusMsg(null)
    },
  })

  function set<K extends keyof DeviceFingerprint>(key: K, value: DeviceFingerprint[K]) {
    setForm((prev) => ({ ...prev, [key]: value }))
  }

  if (isLoading || !fp) {
    return (
      <div className="card flex items-center justify-center h-48">
        <Loader2 className="w-8 h-8 animate-spin text-blue-400" />
      </div>
    )
  }

  return (
    <div className="card space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h3 className="font-semibold text-gray-200">Device fingerprint</h3>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            className="btn-secondary btn-sm"
            onClick={() => randomMutation.mutate(false)}
            disabled={randomMutation.isPending}
          >
            {randomMutation.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Shuffle className="w-4 h-4" />}
            Randomize All
          </button>
          <button
            type="button"
            className="btn-secondary btn-sm"
            onClick={() => randomMutation.mutate(true)}
            disabled={randomMutation.isPending || !isRunning}
            title={!isRunning ? 'Start device to apply' : undefined}
          >
            Randomize + Apply
          </button>
          <button
            type="button"
            className="btn-primary btn-sm"
            onClick={() => saveMutation.mutate()}
            disabled={saveMutation.isPending}
          >
            {saveMutation.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
            Save
          </button>
          <button
            type="button"
            className="btn-success btn-sm"
            onClick={() => applyMutation.mutate()}
            disabled={applyMutation.isPending || !isRunning}
          >
            {applyMutation.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
            Apply to Device
          </button>
        </div>
      </div>

      {(error || statusMsg) && (
        <div
          className={clsx(
            'flex items-start gap-2 rounded-lg border px-3 py-2 text-sm',
            error ? 'border-red-800 bg-red-900/20 text-red-300' : 'border-green-800 bg-green-900/20 text-green-300'
          )}
        >
          {error ? <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" /> : null}
          <span>{error || statusMsg}</span>
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div>
          <label className="label">Device model (profile)</label>
          <select
            className="input"
            value={form.device_model ?? ''}
            onChange={(e) => {
              const v = e.target.value
              set('device_model', v || null)
              if (v) applyProfileModel(v)
            }}
          >
            <option value="">Custom / other</option>
            {profileOptions.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="label">Manufacturer</label>
          <input className="input" value={form.manufacturer ?? ''} onChange={(e) => set('manufacturer', e.target.value || null)} />
        </div>
        <div>
          <label className="label">Brand</label>
          <input className="input" value={form.brand ?? ''} onChange={(e) => set('brand', e.target.value || null)} />
        </div>
        <div>
          <label className="label">Codename</label>
          <input className="input" value={form.device_codename ?? ''} onChange={(e) => set('device_codename', e.target.value || null)} />
        </div>
        <div className="md:col-span-2">
          <label className="label">Build fingerprint</label>
          <input className="input font-mono text-xs" value={form.build_fingerprint ?? ''} onChange={(e) => set('build_fingerprint', e.target.value || null)} />
        </div>
        <div>
          <label className="label">IMEI (15 digits)</label>
          <input className="input font-mono" value={form.imei ?? ''} onChange={(e) => set('imei', e.target.value || null)} />
        </div>
        <div>
          <label className="label">Android ID (16 hex)</label>
          <input className="input font-mono" value={form.android_id ?? ''} onChange={(e) => set('android_id', e.target.value || null)} />
        </div>
        <div>
          <label className="label">MAC address</label>
          <input className="input font-mono" value={form.mac_address ?? ''} onChange={(e) => set('mac_address', e.target.value || null)} />
        </div>
        <div>
          <label className="label">Serial number</label>
          <input className="input font-mono" value={form.serial_number ?? ''} onChange={(e) => set('serial_number', e.target.value || null)} />
        </div>
        <div>
          <label className="label">SDK version</label>
          <input
            type="number"
            className="input"
            value={form.sdk_version ?? ''}
            onChange={(e) => set('sdk_version', e.target.value ? Number(e.target.value) : null)}
          />
        </div>
        <div>
          <label className="label">Android version</label>
          <input className="input" value={form.android_version ?? ''} onChange={(e) => set('android_version', e.target.value || null)} />
        </div>
        <div>
          <label className="label">AP version (Samsung)</label>
          <input className="input font-mono text-sm" value={form.ap_version ?? ''} onChange={(e) => set('ap_version', e.target.value || null)} placeholder="G996BXXSJHZC2" />
        </div>
        <div>
          <label className="label">CSC version (Samsung)</label>
          <input className="input font-mono text-sm" value={form.csc_version ?? ''} onChange={(e) => set('csc_version', e.target.value || null)} placeholder="G996BOXMJHZC2" />
        </div>
        <div>
          <label className="label">Latitude</label>
          <input
            type="number"
            step="any"
            className="input"
            value={form.latitude ?? ''}
            onChange={(e) => set('latitude', e.target.value === '' ? null : Number(e.target.value))}
          />
        </div>
        <div>
          <label className="label">Longitude</label>
          <input
            type="number"
            step="any"
            className="input"
            value={form.longitude ?? ''}
            onChange={(e) => set('longitude', e.target.value === '' ? null : Number(e.target.value))}
          />
        </div>
        <div className="md:col-span-2">
          <span className="label block mb-2">Network type</span>
          <div className="flex flex-wrap gap-4">
            {(['WIFI', 'LTE', '5G', '3G'] as const).map((nt) => (
              <label key={nt} className="flex items-center gap-2 text-sm text-gray-300 cursor-pointer">
                <input
                  type="radio"
                  name="net"
                  checked={form.network_type === nt}
                  onChange={() => set('network_type', nt)}
                />
                {nt}
              </label>
            ))}
          </div>
        </div>
        <div>
          <label className="label">IP address</label>
          <input className="input font-mono" value={form.ip_address ?? ''} onChange={(e) => set('ip_address', e.target.value || null)} />
        </div>
        <div>
          <label className="label">Timezone</label>
          <input className="input" value={form.timezone ?? ''} onChange={(e) => set('timezone', e.target.value || null)} />
        </div>
      </div>
    </div>
  )
}
