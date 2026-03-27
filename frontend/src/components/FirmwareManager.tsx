import { useEffect, useMemo, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Download, Trash2, Loader2, AlertCircle, CheckCircle, Play } from 'lucide-react'
import {
  getDeviceProfiles,
  startFirmwareDownload,
  listFirmwareJobs,
  getFirmwareJob,
  cancelFirmwareJob,
  listFirmwarePackages,
} from '../api/client'
import type { FirmwareJob } from '../api/client'
import clsx from 'clsx'

const CSC_CODES = ['XEU', 'BTU', 'XSP', 'XEF', 'KSA', 'UAE', 'EGY', 'XSA', 'DBT', 'GEN']
const CSC_LABELS: Record<string, string> = {
  'XEU': 'Europe (Germany)',
  'BTU': 'UK',
  'XSP': 'Spain',
  'XEF': 'France',
  'KSA': 'Saudi Arabia',
  'UAE': 'UAE',
  'EGY': 'Egypt',
  'XSA': 'Australia',
  'DBT': 'Germany (T-Mobile)',
  'GEN': 'Generic/Unlocked',
}

export default function FirmwareManager() {
  const queryClient = useQueryClient()
  const [selectedModel, setSelectedModel] = useState<string>('SM-G996B')
  const [selectedCsc, setSelectedCsc] = useState<string>('XEU')
  const [customUrl, setCustomUrl] = useState<string>('')
  const [statusMsg, setStatusMsg] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [pollingJobId, setPollingJobId] = useState<string | null>(null)

  const { data: profiles = [] } = useQuery({
    queryKey: ['device-profiles'],
    queryFn: getDeviceProfiles,
  })

  const { data: jobs = [] } = useQuery({
    queryKey: ['firmware-jobs'],
    queryFn: () => listFirmwareJobs(50),
    refetchInterval: 2000,  // Poll jobs every 2s
  })

  const { data: packages = [] } = useQuery({
    queryKey: ['firmware-packages'],
    queryFn: listFirmwarePackages,
    refetchInterval: 5000,  // Poll packages every 5s
  })

  const profileOptions = useMemo(
    () => profiles.map((p) => p.device_model).sort(),
    [profiles]
  )

  const downloadMutation = useMutation({
    mutationFn: () => startFirmwareDownload(selectedModel, selectedCsc, customUrl || undefined),
    onSuccess: (job) => {
      setStatusMsg(`Download started: ${job.model}/${job.csc} (Job: ${job.job_id})`)
      setError(null)
      setCustomUrl('')
      setPollingJobId(job.job_id)
      queryClient.invalidateQueries({ queryKey: ['firmware-jobs'] })
    },
    onError: (e: Error) => {
      setError(String(e))
      setStatusMsg(null)
    },
  })

  const cancelMutation = useMutation({
    mutationFn: (jobId: string) => cancelFirmwareJob(jobId),
    onSuccess: () => {
      setStatusMsg('Download cancelled')
      setError(null)
      queryClient.invalidateQueries({ queryKey: ['firmware-jobs'] })
    },
    onError: (e: Error) => {
      setError(String(e))
    },
  })

  // If we have a polling job and it's done, stop polling
  useEffect(() => {
    if (pollingJobId) {
      const job = jobs.find((j) => j.job_id === pollingJobId)
      if (job && ['done', 'failed', 'cancelled'].includes(job.status)) {
        setPollingJobId(null)
      }
    }
  }, [pollingJobId, jobs])

  return (
    <div className="space-y-6">
      {/* Status Messages */}
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

      {/* Download Form */}
      <div className="card space-y-4">
        <h3 className="font-semibold text-gray-200">Download Firmware</h3>
        <div className="space-y-3">
          <div>
            <label className="label">Device Model</label>
            <select
              value={selectedModel}
              onChange={(e) => setSelectedModel(e.target.value)}
              className="input"
            >
              {profileOptions.map((model) => (
                <option key={model} value={model}>
                  {model}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="label">Region (CSC)</label>
            <select
              value={selectedCsc}
              onChange={(e) => setSelectedCsc(e.target.value)}
              className="input"
            >
              {CSC_CODES.map((code) => (
                <option key={code} value={code}>
                  {code} - {CSC_LABELS[code]}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="label text-xs text-gray-400">Custom URL (Optional)</label>
            <input
              type="text"
              placeholder="e.g., https://example.com/firmware.zip (for fallback)"
              value={customUrl}
              onChange={(e) => setCustomUrl(e.target.value)}
              className="input font-mono text-xs"
            />
          </div>

          <button
            onClick={() => downloadMutation.mutate()}
            disabled={downloadMutation.isPending}
            className="btn-primary w-full"
          >
            {downloadMutation.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Download className="w-4 h-4" />}
            Start Download
          </button>
        </div>
      </div>

      {/* Active Downloads */}
      {jobs.length > 0 && (
        <div className="card space-y-4">
          <h3 className="font-semibold text-gray-200">Downloads</h3>
          <div className="space-y-3">
            {jobs.slice(0, 10).map((job) => (
              <div key={job.job_id} className="border border-gray-700 rounded-lg p-3 space-y-2 bg-gray-900/50">
                <div className="flex items-center justify-between">
                  <div className="flex-1">
                    <p className="text-sm font-mono text-gray-300">
                      {job.model} / {job.csc} · {job.ap_version || '?'}
                    </p>
                    <p className="text-xs text-gray-500">{job.job_id.substring(0, 12)}...</p>
                  </div>
                  <span className={clsx(
                    'text-xs px-2 py-1 rounded',
                    job.status === 'done' && 'bg-green-900/30 text-green-300',
                    job.status === 'downloading' && 'bg-blue-900/30 text-blue-300',
                    job.status === 'verifying' && 'bg-yellow-900/30 text-yellow-300',
                    job.status === 'failed' && 'bg-red-900/30 text-red-300',
                    job.status === 'cancelled' && 'bg-gray-700/30 text-gray-300',
                    job.status === 'needs_url' && 'bg-orange-900/30 text-orange-300',
                    job.status === 'pending' && 'bg-gray-700/30 text-gray-400',
                  )}>
                    {job.status}
                  </span>
                </div>

                {/* Progress bar */}
                {['downloading', 'verifying'].includes(job.status) && (
                  <div className="space-y-1">
                    <div className="w-full bg-gray-800 rounded-full h-2">
                      <div
                        className="bg-blue-500 h-2 rounded-full transition-all"
                        style={{ width: `${job.progress_pct}%` }}
                      />
                    </div>
                    <div className="flex justify-between text-xs text-gray-400">
                      <span>{job.progress_pct.toFixed(1)}%</span>
                      <span>
                        {(job.downloaded_bytes / 1024 / 1024).toFixed(0)}MB
                        {job.total_bytes && ` / ${(job.total_bytes / 1024 / 1024).toFixed(0)}MB`}
                      </span>
                    </div>
                  </div>
                )}

                {/* Hashes */}
                {job.status === 'done' && (
                  <div className="space-y-1 text-xs text-gray-500 font-mono">
                    <p>SHA256: {job.sha256_hash?.substring(0, 16)}...</p>
                    <p>MD5: {job.md5_hash?.substring(0, 16)}...</p>
                  </div>
                )}

                {/* Error */}
                {job.status === 'failed' && (
                  <p className="text-xs text-red-400">{job.error}</p>
                )}

                {/* Needs URL */}
                {job.status === 'needs_url' && (
                  <p className="text-xs text-orange-300">{job.error}</p>
                )}

                {/* Cancel button */}
                {['pending', 'downloading', 'verifying'].includes(job.status) && (
                  <button
                    onClick={() => cancelMutation.mutate(job.job_id)}
                    disabled={cancelMutation.isPending}
                    className="btn-secondary btn-sm w-full"
                  >
                    {cancelMutation.isPending ? <Loader2 className="w-3 h-3 animate-spin" /> : <Trash2 className="w-3 h-3" />}
                    Cancel
                  </button>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Available Packages */}
      {packages.length > 0 && (
        <div className="card space-y-4">
          <h3 className="font-semibold text-gray-200">Available Firmware</h3>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-700">
                  <th className="text-left py-2 px-2 text-gray-400">Model</th>
                  <th className="text-left py-2 px-2 text-gray-400">CSC</th>
                  <th className="text-left py-2 px-2 text-gray-400">AP Version</th>
                  <th className="text-left py-2 px-2 text-gray-400">File</th>
                </tr>
              </thead>
              <tbody>
                {packages.map((pkg, idx) => (
                  <tr key={idx} className="border-b border-gray-800 hover:bg-gray-900/50">
                    <td className="py-2 px-2 text-gray-300">{pkg.device_model}</td>
                    <td className="py-2 px-2 text-gray-300">{pkg.sales_code || '—'}</td>
                    <td className="py-2 px-2 text-gray-300 font-mono text-xs">{pkg.ap_version}</td>
                    <td className="py-2 px-2 text-gray-400 text-xs truncate">{pkg.filename}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Info */}
      <div className="card bg-blue-900/20 border border-blue-800 text-blue-300 text-sm space-y-2">
        <p>
          <strong>Auto-download:</strong> Fetches firmware from Samsung FOTA servers for your chosen region.
        </p>
        <p>
          <strong>Fallback URL:</strong> If Samsung CDN blocks your region, provide a direct link (e.g., from SamFW.com).
        </p>
        <p>
          <strong>Verification:</strong> Files are checked with MD5 + SHA256 during download.
        </p>
        <p>
          <strong>Storage:</strong> Downloaded files go to the <code className="text-blue-200">firmware/</code> directory and auto-scan for use.
        </p>
      </div>
    </div>
  )
}
