export type DeviceStatus = 'created' | 'booting' | 'running' | 'stopped' | 'error'

export interface Device {
  id: number
  name: string
  status: DeviceStatus
  avd_name: string | null
  adb_port: number | null
  adb_serial: string | null
  scrcpy_port: number | null
  qmp_port: number | null
  console_port: number | null
  pid: number | null
  ram_mb: number
  cpu_cores: number
  api_level: number
  arch: string
  owner_id: number
  created_at: string
  updated_at: string
}

export interface DeviceFingerprint {
  id: number
  device_id: number
  imei: string | null
  android_id: string | null
  mac_address: string | null
  device_model: string | null
  manufacturer: string | null
  brand: string | null
  device_codename: string | null
  build_fingerprint: string | null
  sdk_version: number | null
  android_version: string | null
  board: string | null
  hardware: string | null
  serial_number: string | null
  latitude: number | null
  longitude: number | null
  altitude: number | null
  network_type: string | null
  ip_address: string | null
  timezone: string | null
  language: string | null
  country: string | null
  ap_version: string | null
  csc_version: string | null
  updated_at: string
}

export interface ProxyConfig {
  id: number
  device_id: number
  enabled: boolean
  proxy_type: 'http' | 'socks5'
  host: string | null
  port: number | null
  username: string | null
  password: string | null
  mitm_active: boolean
  mitm_port: number | null
  updated_at: string
}

export interface OperationLog {
  id: number
  device_id: number | null
  user_id: number | null
  action: string
  status: 'success' | 'failure' | 'pending'
  detail: string | null
  created_at: string
}

export interface User {
  id: number
  username: string
  email: string
  role: 'admin' | 'user'
  is_active: boolean
  created_at: string
}

export interface AuthResponse {
  access_token: string
  token_type: string
  user_id: number
  username: string
  role: string
}

export interface DeviceCreateForm {
  name: string
  ram_mb: number
  cpu_cores: number
  api_level: number
  arch: string
  preset?: string | null
}

export interface DevicePresetMeta {
  key: string
  label: string
  api_level: number
  arch: string
  device_model: string
  ram_mb?: number
  cpu_cores?: number
}

export interface ShellResult {
  output: string
  exit_code: number
}

export interface PackageList {
  packages: string[]
  count: number
}

export interface InstallResult {
  success: boolean
  message: string
  package: string
}

/** مكتبة APK (مستودع التطبيقات) */
export interface StoredApk {
  id: number
  display_name: string | null
  original_filename: string
  size_bytes: number
  created_at: string
}

export interface DeviceProfileMeta {
  device_model: string
  manufacturer: string
  brand: string
  device_codename: string
  build_fingerprint: string
  sdk_version: number
  android_version: string
  ap_version?: string | null
  csc_version?: string | null
}

export interface WSMessage {
  type: 'status' | 'screenshot' | 'heartbeat' | 'ping' | 'pong' | 'ack' | 'error'
  status?: DeviceStatus
  device_id?: number
  adb_serial?: string
  data?: string       // base64 screenshot
  format?: string
  width?: number
  height?: number
  device_width?: number
  device_height?: number
  action?: string
  message?: string
  reason?: string
}

/** Latest frame from WebSocket live stream (device screen mirror). */
export interface LiveScreenshotFrame {
  dataBase64: string
  width: number
  height: number
  /** دقة الجهاز الفعلية لتحويل إحداثيات اللمس (قد تختلف عن أبعاد الصورة المضغوطة) */
  deviceWidth: number
  deviceHeight: number
  /** image/jpeg أو image/png حسب حقل format من الخادم */
  mimeType?: string
}
