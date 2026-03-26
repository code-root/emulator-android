import { useCallback, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Package,
  Upload,
  Trash2,
  Loader2,
  Download,
  Pencil,
  Check,
  X,
  AlertCircle,
} from 'lucide-react'
import { formatDistanceToNow } from 'date-fns'
import clsx from 'clsx'
import {
  getStoredApks,
  getDevices,
  uploadStoredApk,
  deleteStoredApk,
  patchStoredApk,
  installFromStore,
} from '../api/client'
import type { Device, StoredApk } from '../types'

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / (1024 * 1024)).toFixed(1)} MB`
}

export default function AppStore() {
  const queryClient = useQueryClient()
  const [dragOver, setDragOver] = useState(false)
  const [toast, setToast] = useState<string | null>(null)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [editLabel, setEditLabel] = useState('')

  const { data: apks = [], isLoading: apksLoading } = useQuery({
    queryKey: ['stored-apks'],
    queryFn: getStoredApks,
  })

  const { data: devices = [] } = useQuery({
    queryKey: ['devices'],
    queryFn: getDevices,
  })

  const runningDevices = devices.filter((d: Device) => d.status === 'running')

  const uploadMut = useMutation({
    mutationFn: (f: File) => uploadStoredApk(f),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['stored-apks'] })
      setToast('تم رفع التطبيق إلى المستودع')
    },
    onError: (e: unknown) => {
      const d = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setToast(d || String(e))
    },
  })

  const deleteMut = useMutation({
    mutationFn: deleteStoredApk,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['stored-apks'] })
      setToast('تم حذف الملف من المستودع')
    },
  })

  const installMut = useMutation({
    mutationFn: ({ apkId, deviceId }: { apkId: number; deviceId: number }) =>
      installFromStore(apkId, deviceId),
    onSuccess: (res, { deviceId }) => {
      queryClient.invalidateQueries({ queryKey: ['packages', deviceId] })
      setToast(res.success ? 'تم التثبيت' : res.message || 'فشل التثبيت')
    },
    onError: (e: unknown) => {
      const d = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setToast(d || String(e))
    },
  })

  const patchMut = useMutation({
    mutationFn: ({ id, display_name }: { id: number; display_name: string | null }) =>
      patchStoredApk(id, display_name),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['stored-apks'] })
      setEditingId(null)
      setToast('تم حفظ الاسم المعروض')
    },
  })

  const onFiles = useCallback(
    (files: FileList | null) => {
      const f = files?.[0]
      if (!f) return
      const low = f.name.toLowerCase()
      if (!low.endsWith('.apk') && !low.endsWith('.apkm')) {
        setToast('الملف يجب أن يكون .apk أو .apkm')
        return
      }
      uploadMut.mutate(f)
    },
    [uploadMut]
  )

  function startEdit(row: StoredApk) {
    setEditingId(row.id)
    setEditLabel(row.display_name || '')
  }

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-gray-100 flex items-center gap-2">
          <Package className="w-7 h-7 text-blue-400" />
          مستودع التطبيقات
        </h1>
        <p className="text-gray-500 text-sm mt-1">
          ارفع APK مرة واحدة، ثم ثبّته على أي محاكٍ شغّال دون إعادة الرفع.
        </p>
      </div>

      {toast && (
        <div className="flex items-center justify-between gap-2 text-sm bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-gray-200">
          <span className="flex items-center gap-2">
            <AlertCircle className="w-4 h-4 text-amber-400 shrink-0" />
            {toast}
          </span>
          <button type="button" className="text-gray-500 hover:text-gray-300" onClick={() => setToast(null)}>
            <X className="w-4 h-4" />
          </button>
        </div>
      )}

      <div
        className={clsx(
          'card border-2 border-dashed transition-colors',
          dragOver ? 'border-blue-500 bg-blue-900/10' : 'border-gray-700'
        )}
        onDragOver={(e) => {
          e.preventDefault()
          setDragOver(true)
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          e.preventDefault()
          setDragOver(false)
          onFiles(e.dataTransfer.files)
        }}
      >
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 py-6 px-2">
          <div className="flex items-center gap-3">
            <Upload className="w-10 h-10 text-gray-500" />
            <div>
              <p className="text-gray-200 font-medium">إسقاط APK / APKM أو اختيار ملف</p>
              <p className="text-gray-500 text-xs mt-0.5">
                APKM = حزمة splits (ZIP). التثبيت من المستودع يستخدم install-multiple تلقائياً.
              </p>
            </div>
          </div>
          <label className="btn-primary cursor-pointer shrink-0">
            <input
              type="file"
              accept=".apk,.apkm,application/vnd.android.package-archive"
              className="hidden"
              disabled={uploadMut.isPending}
              onChange={(e) => onFiles(e.target.files)}
            />
            {uploadMut.isPending ? (
              <span className="flex items-center gap-2">
                <Loader2 className="w-4 h-4 animate-spin" /> جاري الرفع…
              </span>
            ) : (
              'رفع APK / APKM'
            )}
          </label>
        </div>
      </div>

      <div className="card overflow-hidden">
        <h2 className="text-lg font-semibold text-gray-100 px-4 py-3 border-b border-gray-800">
          التطبيقات المحفوظة ({apks.length})
        </h2>
        {apksLoading ? (
          <div className="flex justify-center py-16 text-gray-500">
            <Loader2 className="w-8 h-8 animate-spin" />
          </div>
        ) : apks.length === 0 ? (
          <p className="text-gray-500 text-sm py-12 text-center">لا توجد تطبيقات بعد — ارفع أول APK.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-gray-500 border-b border-gray-800">
                  <th className="px-4 py-3 font-medium">اسم / ملاحظة</th>
                  <th className="px-4 py-3 font-medium">الملف الأصلي</th>
                  <th className="px-4 py-3 font-medium">الحجم</th>
                  <th className="px-4 py-3 font-medium">التاريخ</th>
                  <th className="px-4 py-3 font-medium">تثبيت</th>
                  <th className="px-4 py-3 font-medium w-24"></th>
                </tr>
              </thead>
              <tbody>
                {apks.map((row) => (
                  <tr key={row.id} className="border-b border-gray-800/80 hover:bg-gray-900/40">
                    <td className="px-4 py-3 text-gray-200">
                      {editingId === row.id ? (
                        <div className="flex items-center gap-1">
                          <input
                            className="input text-xs py-1"
                            value={editLabel}
                            onChange={(e) => setEditLabel(e.target.value)}
                            placeholder="اسم معروض"
                          />
                          <button
                            type="button"
                            className="p-1 text-green-400 hover:bg-gray-800 rounded"
                            onClick={() =>
                              patchMut.mutate({
                                id: row.id,
                                display_name: editLabel.trim() || null,
                              })
                            }
                          >
                            <Check className="w-4 h-4" />
                          </button>
                          <button
                            type="button"
                            className="p-1 text-gray-500 hover:bg-gray-800 rounded"
                            onClick={() => setEditingId(null)}
                          >
                            <X className="w-4 h-4" />
                          </button>
                        </div>
                      ) : (
                        <div className="flex items-center gap-2">
                          <span>{row.display_name || '—'}</span>
                          <button
                            type="button"
                            className="text-gray-600 hover:text-blue-400"
                            title="تعديل الاسم المعروض"
                            onClick={() => startEdit(row)}
                          >
                            <Pencil className="w-3.5 h-3.5" />
                          </button>
                        </div>
                      )}
                    </td>
                    <td className="px-4 py-3 text-gray-400 font-mono text-xs truncate max-w-[200px]">
                      {row.original_filename}
                    </td>
                    <td className="px-4 py-3 text-gray-400">{formatBytes(row.size_bytes)}</td>
                    <td className="px-4 py-3 text-gray-500 text-xs">
                      {row.created_at
                        ? formatDistanceToNow(new Date(row.created_at), { addSuffix: true })
                        : '—'}
                    </td>
                    <td className="px-4 py-3">
                      {runningDevices.length === 0 ? (
                        <span className="text-gray-600 text-xs">لا يوجد جهاز شغّال</span>
                      ) : (
                        <div className="flex flex-wrap gap-1">
                          {runningDevices.map((d: Device) => (
                            <button
                              key={d.id}
                              type="button"
                              disabled={installMut.isPending}
                              className="text-xs px-2 py-1 rounded bg-gray-800 text-blue-300 hover:bg-gray-700 border border-gray-700 flex items-center gap-1"
                              title={`تثبيت على ${d.name}`}
                              onClick={() => installMut.mutate({ apkId: row.id, deviceId: d.id })}
                            >
                              <Download className="w-3 h-3" />
                              {d.name}
                            </button>
                          ))}
                        </div>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <button
                        type="button"
                        className="p-2 text-red-400 hover:bg-red-900/20 rounded-lg"
                        title="حذف من المستودع"
                        onClick={() => {
                          if (confirm('حذف هذا APK من المستودع نهائياً؟')) deleteMut.mutate(row.id)
                        }}
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
