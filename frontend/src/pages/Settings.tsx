import { Smartphone, Server, KeyRound } from 'lucide-react'
import { useAuthStore } from '../store/auth'

export default function Settings() {
  const user = useAuthStore((s) => s.user)
  const apiBase =
    import.meta.env.VITE_API_URL !== undefined && String(import.meta.env.VITE_API_URL).length > 0
      ? String(import.meta.env.VITE_API_URL)
      : `${window.location.origin} (same-origin via proxy / nginx)`

  return (
    <div className="p-6 max-w-2xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-100">Settings</h1>
        <p className="text-gray-500 text-sm mt-1">Environment and account summary</p>
      </div>

      <div className="card space-y-3">
        <h2 className="font-semibold text-gray-200 flex items-center gap-2">
          <Server className="w-4 h-4" />
          API
        </h2>
        <p className="text-sm text-gray-400">Resolved API base URL</p>
        <p className="font-mono text-xs bg-gray-900 border border-gray-800 rounded-lg p-3 text-blue-300 break-all">
          {apiBase}
        </p>
      </div>

      <div className="card space-y-3">
        <h2 className="font-semibold text-gray-200 flex items-center gap-2">
          <KeyRound className="w-4 h-4" />
          Session
        </h2>
        {user ? (
          <ul className="text-sm text-gray-300 space-y-2">
            <li>
              <span className="text-gray-500">Username:</span> {user.username}
            </li>
            <li>
              <span className="text-gray-500">Email:</span> {user.email}
            </li>
            <li>
              <span className="text-gray-500">Role:</span> {user.role}
            </li>
          </ul>
        ) : (
          <p className="text-gray-500 text-sm">Not signed in</p>
        )}
      </div>

      <div className="card space-y-2">
        <h2 className="font-semibold text-gray-200 flex items-center gap-2">
          <Smartphone className="w-4 h-4" />
          About
        </h2>
        <p className="text-sm text-gray-400">Android Emulator Farm — manage AVD instances, fingerprints, apps, and proxies from one UI.</p>
      </div>
    </div>
  )
}
