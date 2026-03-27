import { useEffect, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Play, Square, Copy, Download, AlertCircle, CheckCircle, Loader2, Zap } from 'lucide-react'
import {
  getFridaStatus,
  listFridaProcesses,
  attachFrida,
  detachFrida,
  injectFridaScript,
  getFridaScript,
  pushFridaScript,
} from '../api/client'
import clsx from 'clsx'

interface Props {
  deviceId: number
  isRunning: boolean
}

export default function FridaManager({ deviceId, isRunning }: Props) {
  const queryClient = useQueryClient()
  const [selectedProcess, setSelectedProcess] = useState<string>('zygote')
  const [scriptCode, setScriptCode] = useState<string>('')
  const [scriptType, setScriptType] = useState<'anti_detect' | 'custom'>('anti_detect')
  const [error, setError] = useState<string | null>(null)
  const [statusMsg, setStatusMsg] = useState<string | null>(null)
  const [pidInput, setPidInput] = useState<string>('')

  // Queries
  const { data: fridaStatus, refetch: refetchStatus } = useQuery({
    queryKey: ['frida-status', deviceId],
    queryFn: () => getFridaStatus(deviceId),
    enabled: isRunning,
    refetchInterval: 5000,
  })

  const { data: processes } = useQuery({
    queryKey: ['frida-processes', deviceId],
    queryFn: () => listFridaProcesses(deviceId),
    enabled: isRunning,
  })

  const { data: fridaScript } = useQuery({
    queryKey: ['frida-script', deviceId],
    queryFn: () => getFridaScript(deviceId),
    enabled: isRunning,
  })

  // Mutations
  const attachMutation = useMutation({
    mutationFn: () =>
      attachFrida(deviceId, {
        process_name: selectedProcess,
        script_type: scriptType,
        script_code: scriptType === 'custom' ? scriptCode : undefined,
      }),
    onSuccess: () => {
      setStatusMsg('Script injected successfully')
      setError(null)
      setTimeout(() => refetchStatus(), 1000)
    },
    onError: (e: Error) => {
      setError(String(e))
    },
  })

  const detachMutation = useMutation({
    mutationFn: () => detachFrida(deviceId),
    onSuccess: () => {
      setStatusMsg('Frida session detached')
      setError(null)
      setTimeout(() => refetchStatus(), 1000)
    },
    onError: (e: Error) => {
      setError(String(e))
    },
  })

  const injectMutation = useMutation({
    mutationFn: () => {
      const pid = parseInt(pidInput, 10)
      if (isNaN(pid)) throw new Error('Invalid PID')
      return injectFridaScript(deviceId, pid, scriptCode)
    },
    onSuccess: () => {
      setStatusMsg('Script injected to process')
      setError(null)
    },
    onError: (e: Error) => {
      setError(String(e))
    },
  })

  const pushMutation = useMutation({
    mutationFn: () => pushFridaScript(deviceId),
    onSuccess: (data) => {
      setStatusMsg(`Script pushed: ${data.remote_path}`)
      setError(null)
    },
    onError: (e: Error) => {
      setError(String(e))
    },
  })

  function copyScriptToClipboard() {
    if (fridaScript?.script) {
      navigator.clipboard.writeText(fridaScript.script)
      setStatusMsg('Script copied to clipboard')
    }
  }

  function downloadScript() {
    if (fridaScript?.script) {
      const element = document.createElement('a')
      element.setAttribute('href', 'data:text/plain;charset=utf-8,' + encodeURIComponent(fridaScript.script))
      element.setAttribute('download', 'anti_detect.js')
      element.style.display = 'none'
      document.body.appendChild(element)
      element.click()
      document.body.removeChild(element)
    }
  }

  if (!isRunning) {
    return (
      <div className="card text-center py-8">
        <p className="text-gray-400">Start the device to use Frida</p>
      </div>
    )
  }

  const isActive = fridaStatus?.active ?? false
  const processList = processes?.processes ?? []

  return (
    <div className="space-y-6">
      {/* Status Bar */}
      <div className="card bg-gray-900">
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2">
            {isActive ? (
              <>
                <div className="w-3 h-3 rounded-full bg-green-500 animate-pulse" />
                <span className="text-green-400 font-semibold">Active (PID: {fridaStatus?.pid})</span>
              </>
            ) : (
              <>
                <div className="w-3 h-3 rounded-full bg-gray-500" />
                <span className="text-gray-400">Inactive</span>
              </>
            )}
          </div>
        </div>
      </div>

      {(error || statusMsg) && (
        <div
          className={clsx(
            'flex items-start gap-2 rounded-lg border px-3 py-2 text-sm',
            error ? 'border-red-800 bg-red-900/20 text-red-300' : 'border-green-800 bg-green-900/20 text-green-300'
          )}
        >
          {error ? <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" /> : <CheckCircle className="w-4 h-4 shrink-0 mt-0.5" />}
          <span>{error || statusMsg}</span>
        </div>
      )}

      {/* Quick Actions */}
      <div className="card space-y-4">
        <h3 className="font-semibold text-gray-200">Quick Actions</h3>
        <div className="flex flex-wrap gap-2">
          <button
            onClick={() => attachMutation.mutate()}
            disabled={attachMutation.isPending || isActive}
            className="btn-success btn-sm"
          >
            {attachMutation.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Zap className="w-4 h-4" />}
            Inject Anti-Detect
          </button>
          {isActive && (
            <button
              onClick={() => detachMutation.mutate()}
              disabled={detachMutation.isPending}
              className="btn-secondary btn-sm"
            >
              {detachMutation.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Square className="w-4 h-4" />}
              Stop Session
            </button>
          )}
          <button
            onClick={() => pushMutation.mutate()}
            disabled={pushMutation.isPending}
            className="btn-secondary btn-sm"
          >
            {pushMutation.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Download className="w-4 h-4" />}
            Push Script Only
          </button>
        </div>
      </div>

      {/* Process Picker */}
      <div className="card space-y-3">
        <h3 className="font-semibold text-gray-200">Attach to Process</h3>
        <div className="flex flex-col gap-3">
          <div>
            <label className="label">Process name (or select from list)</label>
            <select
              value={selectedProcess}
              onChange={(e) => setSelectedProcess(e.target.value)}
              className="input"
              disabled={isActive}
            >
              <option value="zygote">zygote (system service)</option>
              {processList.map((p) => (
                <option key={p.pid} value={p.name}>
                  {p.name} (PID: {p.pid})
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="label text-xs text-gray-400 mb-2">Or enter app package</label>
            <input
              type="text"
              className="input"
              placeholder="com.example.app"
              value={selectedProcess}
              onChange={(e) => setSelectedProcess(e.target.value)}
              disabled={isActive}
            />
          </div>
        </div>
      </div>

      {/* Script Type & Injection */}
      <div className="card space-y-4">
        <h3 className="font-semibold text-gray-200">Script Injection</h3>

        {/* Script Type Tabs */}
        <div className="flex gap-2 border-b border-gray-800">
          <button
            onClick={() => setScriptType('anti_detect')}
            className={clsx(
              'px-3 py-2 text-sm border-b-2 transition',
              scriptType === 'anti_detect'
                ? 'border-blue-500 text-blue-400'
                : 'border-transparent text-gray-400 hover:text-gray-300'
            )}
          >
            Anti-Detect (Preset)
          </button>
          <button
            onClick={() => setScriptType('custom')}
            className={clsx(
              'px-3 py-2 text-sm border-b-2 transition',
              scriptType === 'custom'
                ? 'border-blue-500 text-blue-400'
                : 'border-transparent text-gray-400 hover:text-gray-300'
            )}
          >
            Custom Script
          </button>
        </div>

        {scriptType === 'anti_detect' ? (
          // Anti-Detect Preview
          <div className="space-y-3">
            <p className="text-xs text-gray-400">Automatically generated anti-emulator detection hooks from your device fingerprint.</p>
            <div className="flex flex-wrap gap-2">
              <button onClick={copyScriptToClipboard} className="btn-secondary btn-sm">
                <Copy className="w-4 h-4" /> Copy
              </button>
              <button onClick={downloadScript} className="btn-secondary btn-sm">
                <Download className="w-4 h-4" /> Download
              </button>
            </div>
            {fridaScript && (
              <pre className="bg-gray-950 border border-gray-800 rounded p-3 overflow-x-auto text-xs max-h-64 overflow-y-auto">
                {fridaScript.script.substring(0, 500)}
                {fridaScript.script.length > 500 && `\n... (${fridaScript.script.length} chars total)`}
              </pre>
            )}
          </div>
        ) : (
          // Custom Script Editor
          <div className="space-y-3">
            <textarea
              className="input font-mono text-xs h-40"
              placeholder="Enter custom Frida script..."
              value={scriptCode}
              onChange={(e) => setScriptCode(e.target.value)}
            />
          </div>
        )}
      </div>

      {/* Inject Buttons */}
      <div className="card space-y-3">
        <h3 className="font-semibold text-gray-200">Inject Method</h3>
        <div className="space-y-3">
          {/* Method 1: Attach to Process */}
          <div>
            <p className="text-sm text-gray-400 mb-2">Method 1: Attach to process (automatic)</p>
            <button
              onClick={() => attachMutation.mutate()}
              disabled={attachMutation.isPending || isActive}
              className="btn-primary btn-sm w-full"
            >
              {attachMutation.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
              Attach & Inject
            </button>
          </div>

          {/* Method 2: Inject by PID */}
          {scriptType === 'custom' && (
            <div>
              <p className="text-sm text-gray-400 mb-2">Method 2: Inject into running process by PID</p>
              <div className="flex gap-2">
                <input
                  type="number"
                  className="input flex-1"
                  placeholder="Enter process PID"
                  value={pidInput}
                  onChange={(e) => setPidInput(e.target.value)}
                />
                <button
                  onClick={() => injectMutation.mutate()}
                  disabled={injectMutation.isPending || !pidInput}
                  className="btn-secondary btn-sm"
                >
                  {injectMutation.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : 'Inject'}
                </button>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Info */}
      <div className="card bg-blue-900/20 border border-blue-800 text-blue-300 text-sm space-y-2">
        <p>
          <strong>Frida:</strong> Dynamic instrumentation tool for runtime patching. Requires frida-server on device.
        </p>
        <p>
          <strong>Anti-Detect:</strong> Hooks Java APIs to spoof Build properties, IMEI, MAC, GPS, and more to avoid emulator detection.
        </p>
        <p>
          <strong>Custom:</strong> Write your own JavaScript hooks using the Frida API.
        </p>
      </div>
    </div>
  )
}
