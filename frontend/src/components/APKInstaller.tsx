import { useCallback, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Upload, Trash2, Loader2, Package, AlertCircle } from 'lucide-react'
import { installAPK, getPackages, uninstallPackage } from '../api/client'
import clsx from 'clsx'

interface Props {
  deviceId: number
  isRunning: boolean
}

export default function APKInstaller({ deviceId, isRunning }: Props) {
  const queryClient = useQueryClient()
  const [dragOver, setDragOver] = useState(false)
  const [progress, setProgress] = useState(0)
  const [lastMessage, setLastMessage] = useState<string | null>(null)

  const { data: pkgData, isLoading: pkgsLoading } = useQuery({
    queryKey: ['packages', deviceId],
    queryFn: () => getPackages(deviceId),
    enabled: isRunning,
    refetchInterval: 30_000,
  })

  const installMutation = useMutation({
    mutationFn: (file: File) => installAPK(deviceId, file, setProgress),
    onSuccess: (res) => {
      setLastMessage(res.message || (res.success ? 'Installed' : 'Install reported failure'))
      setProgress(0)
      queryClient.invalidateQueries({ queryKey: ['packages', deviceId] })
    },
    onError: (e: unknown) => {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setLastMessage(msg || String(e))
      setProgress(0)
    },
  })

  const uninstallMutation = useMutation({
    mutationFn: (pkg: string) => uninstallPackage(deviceId, pkg),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['packages', deviceId] })
    },
  })

  const onFile = useCallback(
    (files: FileList | null) => {
      if (!files?.length || !isRunning) return
      const f = files[0]
      const n = f.name.toLowerCase()
      if (!n.endsWith('.apk') && !n.endsWith('.apkm')) {
        setLastMessage('اختر ملف .apk أو حزمة .apkm (ZIP يحتوي splits)')
        return
      }
      setLastMessage(null)
      installMutation.mutate(f)
    },
    [deviceId, isRunning, installMutation]
  )

  return (
    <div className="space-y-6">
      <div
        className={clsx(
          'card border-2 border-dashed transition-colors',
          dragOver ? 'border-blue-500 bg-blue-900/10' : 'border-gray-700',
          !isRunning && 'opacity-60 pointer-events-none'
        )}
        onDragOver={(e) => {
          e.preventDefault()
          setDragOver(true)
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          e.preventDefault()
          setDragOver(false)
          onFile(e.dataTransfer.files)
        }}
      >
        <div className="flex flex-col items-center py-10 text-center">
          <Upload className="w-10 h-10 text-gray-500 mb-3" />
          <p className="text-gray-300 font-medium">أسقِط APK / APKM أو اختر ملفاً</p>
          <p className="text-gray-500 text-sm mt-1">
            APKM = أرشيف ZIP فيه عدة ملفات .apk (splits). النسخ المشفّرة من المتجر لا تُدعم — صدّر ZIP من APKMirror
            Installer.
          </p>
          <label className="btn-primary mt-4 cursor-pointer">
            <input
              type="file"
              accept=".apk,.apkm,application/vnd.android.package-archive"
              className="hidden"
              disabled={!isRunning || installMutation.isPending}
              onChange={(e) => onFile(e.target.files)}
            />
            Select APK
          </label>
        </div>
        {installMutation.isPending && (
          <div className="px-6 pb-6">
            <div className="h-2 bg-gray-800 rounded-full overflow-hidden">
              <div className="h-full bg-blue-600 transition-all" style={{ width: `${progress}%` }} />
            </div>
            <p className="text-xs text-gray-500 mt-2 text-center">{progress}% uploaded</p>
          </div>
        )}
      </div>

      {lastMessage && (
        <div className="flex items-start gap-2 text-sm text-amber-200 bg-amber-900/20 border border-amber-800 rounded-lg px-3 py-2">
          <AlertCircle className="w-4 h-4 shrink-0" />
          {lastMessage}
        </div>
      )}

      <div className="card">
        <div className="flex items-center justify-between mb-4">
          <h3 className="font-semibold text-gray-200 flex items-center gap-2">
            <Package className="w-4 h-4" />
            Installed packages
          </h3>
          {!isRunning && <span className="text-xs text-gray-500">Start device to load</span>}
        </div>
        {!isRunning ? (
          <p className="text-gray-500 text-sm">Device must be running.</p>
        ) : pkgsLoading ? (
          <div className="flex justify-center py-8">
            <Loader2 className="w-6 h-6 animate-spin text-blue-400" />
          </div>
        ) : (
          <div className="max-h-80 overflow-y-auto space-y-1 font-mono text-xs">
            {(pkgData?.packages ?? []).map((pkg) => (
              <div
                key={pkg}
                className="flex items-center justify-between gap-2 py-1.5 px-2 rounded hover:bg-gray-800/50"
              >
                <span className="text-gray-300 truncate">{pkg}</span>
                <button
                  type="button"
                  className="btn-danger btn-sm shrink-0"
                  disabled={uninstallMutation.isPending}
                  onClick={() => {
                    if (confirm(`Uninstall ${pkg}?`)) uninstallMutation.mutate(pkg)
                  }}
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </div>
            ))}
            {pkgData && pkgData.count === 0 && <p className="text-gray-500">No packages returned.</p>}
          </div>
        )}
      </div>
    </div>
  )
}
