import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ScrollText, Copy, Filter, Loader2 } from 'lucide-react'
import { getLogcat } from '../api/client'
import clsx from 'clsx'

interface Props {
  deviceId: number
  isRunning: boolean
}

type LevelFilter = 'ALL' | 'INFO' | 'ERROR' | 'DEBUG'

function detectLevel(line: string): LevelFilter {
  const u = line.toUpperCase()
  if (u.includes(' E/') || u.includes('ERROR') || u.includes(' FATAL')) return 'ERROR'
  if (u.includes(' D/') || u.includes('DEBUG')) return 'DEBUG'
  if (u.includes(' I/') || u.includes('INFO')) return 'INFO'
  return 'INFO'
}

export default function LogsViewer({ deviceId, isRunning }: Props) {
  const [autoScroll, setAutoScroll] = useState(true)
  const [level, setLevel] = useState<LevelFilter>('ALL')
  const bottomRef = useRef<HTMLDivElement>(null)

  const { data, isLoading, refetch, isFetching } = useQuery({
    queryKey: ['logcat', deviceId],
    queryFn: () => getLogcat(deviceId, 100),
    enabled: isRunning,
    refetchInterval: isRunning ? 5_000 : false,
  })

  const lines = data?.lines ?? []

  const filtered = useMemo(() => {
    if (level === 'ALL') return lines
    return lines.filter((l) => detectLevel(l) === level)
  }, [lines, level])

  useEffect(() => {
    if (autoScroll && bottomRef.current) {
      bottomRef.current.scrollIntoView({ behavior: 'smooth' })
    }
  }, [filtered, autoScroll])

  async function copyAll() {
    await navigator.clipboard.writeText(filtered.join('\n'))
  }

  return (
    <div className="card space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h3 className="font-semibold text-gray-200 flex items-center gap-2">
          <ScrollText className="w-4 h-4" />
          Logcat (last 100 lines)
        </h3>
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex items-center gap-1 text-sm text-gray-400">
            <Filter className="w-4 h-4" />
            <select
              className="input py-1 text-xs"
              value={level}
              onChange={(e) => setLevel(e.target.value as LevelFilter)}
            >
              {(['ALL', 'INFO', 'ERROR', 'DEBUG'] as const).map((l) => (
                <option key={l} value={l}>
                  {l}
                </option>
              ))}
            </select>
          </div>
          <label className="flex items-center gap-2 text-xs text-gray-400 cursor-pointer">
            <input type="checkbox" checked={autoScroll} onChange={(e) => setAutoScroll(e.target.checked)} />
            Auto-scroll
          </label>
          <button type="button" className="btn-secondary btn-sm" onClick={() => refetch()} disabled={!isRunning}>
            {isFetching ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : 'Refresh'}
          </button>
          <button type="button" className="btn-secondary btn-sm" onClick={copyAll} disabled={!filtered.length}>
            <Copy className="w-3.5 h-3.5" />
            Copy
          </button>
        </div>
      </div>

      {!isRunning ? (
        <p className="text-gray-500 text-sm">Start the device to stream logcat.</p>
      ) : isLoading ? (
        <div className="flex justify-center py-12">
          <Loader2 className="w-8 h-8 animate-spin text-blue-400" />
        </div>
      ) : (
        <div
          className={clsx(
            'font-mono text-xs bg-gray-950 border border-gray-800 rounded-lg p-3 h-96 overflow-y-auto',
            'text-gray-300 whitespace-pre-wrap break-all'
          )}
        >
          {filtered.map((line, i) => (
            <div
              key={`${i}-${line.slice(0, 24)}`}
              className={clsx(
                'py-0.5 border-b border-gray-800/50',
                detectLevel(line) === 'ERROR' && 'text-red-400',
                detectLevel(line) === 'DEBUG' && 'text-gray-500'
              )}
            >
              {line}
            </div>
          ))}
          <div ref={bottomRef} />
        </div>
      )}
    </div>
  )
}
