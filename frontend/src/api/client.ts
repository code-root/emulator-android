import axios, { AxiosProgressEvent } from 'axios'
import type {
  AuthResponse,
  Device,
  DeviceCreateForm,
  DeviceFingerprint,
  DevicePresetMeta,
  DeviceProfileMeta,
  FirmwarePackageMeta,
  InstallResult,
  OperationLog,
  PackageList,
  ProxyConfig,
  ShellResult,
  User,
  StoredApk,
} from '../types'

const RAW_API = import.meta.env.VITE_API_URL
const BASE_URL =
  RAW_API !== undefined && RAW_API !== null && String(RAW_API).length > 0
    ? String(RAW_API).replace(/\/$/, '')
    : ''

export const apiClient = axios.create({
  baseURL: BASE_URL,
  timeout: 30_000,
})

// Request interceptor — attach JWT token
apiClient.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// Response interceptor — handle 401
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('token')
      localStorage.removeItem('user')
      window.location.href = '/login'
    }
    return Promise.reject(error)
  }
)

// ─── Auth ──────────────────────────────────────────────────────────────────
export async function login(username: string, password: string): Promise<AuthResponse> {
  const res = await apiClient.post<AuthResponse>('/api/auth/login', { username, password })
  return res.data
}

export async function register(username: string, email: string, password: string): Promise<User> {
  const res = await apiClient.post<User>('/api/auth/register', { username, email, password })
  return res.data
}

export async function getMe(): Promise<User> {
  const res = await apiClient.get<User>('/api/auth/me')
  return res.data
}

// ─── Devices ───────────────────────────────────────────────────────────────
export async function getDevices(): Promise<Device[]> {
  const res = await apiClient.get<Device[]>('/api/devices')
  return res.data
}

export async function getDevice(id: number): Promise<Device> {
  const res = await apiClient.get<Device>(`/api/devices/${id}`)
  return res.data
}

export async function createDevice(data: DeviceCreateForm): Promise<Device> {
  const res = await apiClient.post<Device>('/api/devices', data)
  return res.data
}

export async function deleteDevice(id: number): Promise<void> {
  await apiClient.delete(`/api/devices/${id}`)
}

export async function startDevice(id: number): Promise<Device> {
  const res = await apiClient.post<Device>(`/api/devices/${id}/start`)
  return res.data
}

export async function stopDevice(id: number): Promise<Device> {
  const res = await apiClient.post<Device>(`/api/devices/${id}/stop`)
  return res.data
}

export async function restartDevice(id: number): Promise<Device> {
  const res = await apiClient.post<Device>(`/api/devices/${id}/restart`)
  return res.data
}

export async function executeShell(id: number, cmd: string): Promise<ShellResult> {
  const res = await apiClient.post<ShellResult>(`/api/devices/${id}/shell`, { cmd })
  return res.data
}

export async function getScreenshot(id: number): Promise<Blob> {
  try {
    const res = await apiClient.get(`/api/devices/${id}/screenshot`, {
      responseType: 'blob',
    })
    return res.data
  } catch (err) {
    if (axios.isAxiosError(err) && err.response?.status === 503) {
      const data = err.response.data
      let msg = 'الجهاز غير متصل بـ ADB'
      if (data instanceof Blob) {
        try {
          const text = await data.text()
          const j = JSON.parse(text) as { detail?: string }
          if (typeof j.detail === 'string' && j.detail.length) msg = j.detail
        } catch {
          /* ignore */
        }
      }
      throw new Error(msg)
    }
    throw err
  }
}

export async function getDeviceLogs(id: number, limit = 100): Promise<OperationLog[]> {
  const res = await apiClient.get<OperationLog[]>(`/api/devices/${id}/logs?limit=${limit}`)
  return res.data
}

export async function getLogcat(id: number, lines = 100): Promise<{ lines: string[]; total: number }> {
  const res = await apiClient.get(`/api/devices/${id}/logcat?lines=${lines}`)
  return res.data
}

// ─── Fingerprint ──────────────────────────────────────────────────────────
export async function getFingerprint(id: number): Promise<DeviceFingerprint> {
  const res = await apiClient.get<DeviceFingerprint>(`/api/devices/${id}/fingerprint`)
  return res.data
}

export async function updateFingerprint(
  id: number,
  data: Partial<DeviceFingerprint>
): Promise<DeviceFingerprint> {
  const res = await apiClient.put<DeviceFingerprint>(`/api/devices/${id}/fingerprint`, data)
  return res.data
}

export async function applyFingerprint(id: number): Promise<{
  success: boolean
  report: { applied?: string[]; failed?: string[]; warnings?: string[] }
  samsung_extended_spoof?: boolean
  note?: string | null
  detail?: string | null
}> {
  const res = await apiClient.post(`/api/devices/${id}/fingerprint/apply`)
  return res.data
}

export async function randomizeFingerprint(id: number, apply = false): Promise<DeviceFingerprint> {
  const res = await apiClient.post<DeviceFingerprint>(
    `/api/devices/${id}/fingerprint/randomize?apply=${apply}`
  )
  return res.data
}

// ─── Apps ─────────────────────────────────────────────────────────────────
export async function installAPK(
  id: number,
  file: File,
  onProgress?: (progress: number) => void
): Promise<InstallResult> {
  const formData = new FormData()
  formData.append('file', file)
  const res = await apiClient.post<InstallResult>(`/api/devices/${id}/install`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    onUploadProgress: (evt: AxiosProgressEvent) => {
      if (onProgress && evt.total) {
        onProgress(Math.round((evt.loaded * 100) / evt.total))
      }
    },
  })
  return res.data
}

export async function getPackages(id: number): Promise<PackageList> {
  const res = await apiClient.get<PackageList>(`/api/devices/${id}/packages`)
  return res.data
}

export async function uninstallPackage(
  id: number,
  pkg: string
): Promise<{ success: boolean; message: string }> {
  const res = await apiClient.delete(`/api/devices/${id}/packages/${pkg}`)
  return res.data
}

// ─── APK Store (مستودع التطبيقات) ───────────────────────────────────────────
export async function getStoredApks(): Promise<StoredApk[]> {
  const res = await apiClient.get<StoredApk[]>('/api/store/apks')
  return res.data
}

export async function uploadStoredApk(file: File): Promise<StoredApk> {
  const form = new FormData()
  form.append('file', file)
  const res = await apiClient.post<StoredApk>('/api/store/apks', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 600_000,
  })
  return res.data
}

export async function deleteStoredApk(id: number): Promise<void> {
  await apiClient.delete(`/api/store/apks/${id}`)
}

export async function patchStoredApk(id: number, display_name: string | null): Promise<StoredApk> {
  const res = await apiClient.patch<StoredApk>(`/api/store/apks/${id}`, { display_name })
  return res.data
}

export async function installFromStore(apkId: number, deviceId: number): Promise<InstallResult> {
  const res = await apiClient.post<InstallResult>(`/api/store/apks/${apkId}/install/${deviceId}`)
  return res.data
}

// ─── Proxy ─────────────────────────────────────────────────────────────────
export async function getProxy(id: number): Promise<ProxyConfig> {
  const res = await apiClient.get<ProxyConfig>(`/api/devices/${id}/proxy`)
  return res.data
}

export async function setProxy(
  id: number,
  config: Partial<ProxyConfig>
): Promise<ProxyConfig> {
  const res = await apiClient.put<ProxyConfig>(`/api/devices/${id}/proxy`, config)
  return res.data
}

export async function startMitmProxy(id: number): Promise<{ success: boolean; port: number; pid: number }> {
  const res = await apiClient.post(`/api/devices/${id}/proxy/start`)
  return res.data
}

export async function stopMitmProxy(id: number): Promise<{ success: boolean }> {
  const res = await apiClient.post(`/api/devices/${id}/proxy/stop`)
  return res.data
}

export async function getProxyTraffic(id: number, limit = 100): Promise<{ entries: string[]; count: number }> {
  const res = await apiClient.get(`/api/devices/${id}/proxy/traffic?limit=${limit}`)
  return res.data
}

export async function getRecentOperationLogs(limit = 50): Promise<OperationLog[]> {
  const res = await apiClient.get<OperationLog[]>(`/api/operation-logs/recent?limit=${limit}`)
  return res.data
}

export async function getDeviceProfiles(): Promise<DeviceProfileMeta[]> {
  const res = await apiClient.get<DeviceProfileMeta[]>('/api/meta/device-profiles')
  return res.data
}

export async function getDevicePresets(): Promise<DevicePresetMeta[]> {
  const res = await apiClient.get<DevicePresetMeta[]>('/api/meta/device-presets')
  return res.data
}

export async function getFirmwarePackages(): Promise<FirmwarePackageMeta[]> {
  const res = await apiClient.get<FirmwarePackageMeta[]>('/api/meta/firmware-packages')
  return res.data
}

// ─── Countries & GPS/IP ────────────────────────────────────────────────────

export interface CountryData {
  name: string
  country_iso: string
  timezone: string
  language: string
  cities: Array<{ name: string; latitude: number; longitude: number; altitude_m: number }>
  carriers: Array<{ name: string; mcc: string; mnc: string; apn: string }>
  ip_prefixes: string[]
}

export async function listCountries(): Promise<{ countries: Record<string, CountryData> }> {
  const res = await apiClient.get('/api/meta/countries')
  return res.data
}

export interface SamsungFirmwareInfo {
  model: string
  csc: string
  ap_version: string | null
  csc_version: string | null
  full_version: string
}

export async function fetchSamsungFirmware(model: string, csc: string = 'XEU'): Promise<SamsungFirmwareInfo> {
  const res = await apiClient.get<SamsungFirmwareInfo>('/api/meta/samsung-firmware', {
    params: { model, csc },
  })
  return res.data
}

// ─── Fingerprint Randomization ────────────────────────────────────────────

export async function randomizeFingerprintWithCountry(
  id: number,
  deviceModel?: string,
  countryCode?: string,
  apply = false
): Promise<DeviceFingerprint> {
  const params = new URLSearchParams()
  if (deviceModel) params.append('device_model', deviceModel)
  if (countryCode) params.append('country_code', countryCode)
  if (apply) params.append('apply', 'true')

  const res = await apiClient.post<DeviceFingerprint>(
    `/api/fingerprint/${id}/randomize?${params.toString()}`
  )
  return res.data
}

// ─── Frida Management ──────────────────────────────────────────────────────

export interface FridaStatus {
  device_id: number
  active: boolean
  pid: number | null
  serial: string
}

export interface FridaProcess {
  pid: number
  name: string
}

export interface FridaAttachRequest {
  process_name: string
  script_type: 'anti_detect' | 'custom'
  script_code?: string
}

export async function getFridaStatus(id: number): Promise<FridaStatus> {
  const res = await apiClient.get(`/api/devices/${id}/frida/status`)
  return res.data
}

export async function listFridaProcesses(id: number): Promise<{ processes: FridaProcess[] }> {
  const res = await apiClient.get(`/api/devices/${id}/frida/processes`)
  return res.data
}

export async function attachFrida(id: number, body: FridaAttachRequest): Promise<any> {
  const res = await apiClient.post(`/api/devices/${id}/frida/attach`, body)
  return res.data
}

export async function detachFrida(id: number): Promise<{ success: boolean; message: string }> {
  const res = await apiClient.post(`/api/devices/${id}/frida/detach`)
  return res.data
}

export async function injectFridaScript(
  id: number,
  pid: number,
  scriptCode: string
): Promise<any> {
  const res = await apiClient.post(`/api/devices/${id}/frida/inject`, {
    pid,
    script_code: scriptCode,
  })
  return res.data
}

export async function getFridaScript(id: number): Promise<{ device_id: number; script: string; mime_type: string }> {
  const res = await apiClient.get(`/api/devices/${id}/frida/script`)
  return res.data
}

export async function pushFridaScript(id: number): Promise<{ success: boolean; remote_path: string; message: string }> {
  const res = await apiClient.post(`/api/devices/${id}/frida/push-script`)
  return res.data
}

// ─── Firmware Download Management ──────────────────────────────────────────

export interface FirmwareJob {
  job_id: string
  model: string
  csc: string
  ap_version: string | null
  status: 'pending' | 'downloading' | 'verifying' | 'done' | 'failed' | 'cancelled' | 'needs_url'
  progress_pct: number
  downloaded_bytes: number
  total_bytes: number | null
  dest_path: string | null
  error: string | null
  md5_hash: string | null
  sha256_hash: string | null
  requires_url: boolean
}

export async function startFirmwareDownload(
  model: string,
  csc: string,
  url?: string
): Promise<FirmwareJob> {
  const res = await apiClient.post<FirmwareJob>('/api/firmware/download', {
    model,
    csc,
    url,
  })
  return res.data
}

export async function listFirmwareJobs(limit?: number): Promise<FirmwareJob[]> {
  const res = await apiClient.get<FirmwareJob[]>('/api/firmware/jobs', {
    params: limit ? { limit } : undefined,
  })
  return res.data
}

export async function getFirmwareJob(jobId: string): Promise<FirmwareJob> {
  const res = await apiClient.get<FirmwareJob>(`/api/firmware/jobs/${jobId}`)
  return res.data
}

export async function cancelFirmwareJob(jobId: string): Promise<{ success: boolean; job_id: string }> {
  const res = await apiClient.delete(`/api/firmware/jobs/${jobId}`)
  return res.data
}

export async function listFirmwarePackages(): Promise<FirmwarePackageMeta[]> {
  const res = await apiClient.get<FirmwarePackageMeta[]>('/api/firmware/packages')
  return res.data
}

// ─── WebSocket URL helper ──────────────────────────────────────────────────
/**
 * WebSocket origin:
 * - If `VITE_API_URL` is set → same host as REST (recommended in dev).
 * - Vite dev without env → `ws://localhost:8000` (matches vite.config proxy target;
 *   avoids `ws://localhost:5173` + flaky /ws proxy and React StrictMode teardown noise).
 * - Production build without env → same host as the page (reverse-proxy deployment).
 */
function getWebSocketBase(): string {
  if (BASE_URL) {
    return BASE_URL.replace(/\/$/, '').replace(/^http/, 'ws')
  }
  if (typeof window !== 'undefined') {
    if (import.meta.env.DEV) {
      return 'ws://localhost:8000'
    }
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    return `${protocol}//${window.location.host}`
  }
  return 'ws://localhost:8000'
}

export function getWebSocketUrl(deviceId: number): string {
  const token = encodeURIComponent(localStorage.getItem('token') ?? '')
  const base = getWebSocketBase()
  return `${base}/ws/${deviceId}?token=${token}`
}

/** Low-latency H.264 mirror (ADB screenrecord → WebCodecs). See `/ws/{id}/h264`. */
export function getWebSocketH264Url(deviceId: number): string {
  const token = encodeURIComponent(localStorage.getItem('token') ?? '')
  const base = getWebSocketBase()
  return `${base}/ws/${deviceId}/h264?token=${token}`
}
