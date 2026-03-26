import { useState, FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { Smartphone, AlertCircle, Loader2 } from 'lucide-react'
import { login, getMe } from '../api/client'
import { useAuthStore } from '../store/auth'

export default function Login() {
  const navigate = useNavigate()
  const authLogin = useAuthStore((s) => s.login)
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    const u = username.trim()
    const p = password.trim()
    if (!u || !p) {
      setError('Username and password are required')
      return
    }
    setLoading(true)
    setError('')
    try {
      const authRes = await login(u, p)
      // Temporarily store token to fetch user info
      localStorage.setItem('token', authRes.access_token)
      const user = await getMe()
      authLogin(authRes.access_token, user)
      navigate('/dashboard', { replace: true })
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(msg || 'Invalid credentials. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-gray-950 flex items-center justify-center px-4">
      <div className="w-full max-w-sm">
        {/* Logo */}
        <div className="flex flex-col items-center mb-8">
          <div className="w-16 h-16 bg-blue-600 rounded-2xl flex items-center justify-center mb-4 shadow-lg shadow-blue-600/30">
            <Smartphone className="w-8 h-8 text-white" />
          </div>
          <h1 className="text-2xl font-bold text-gray-100">Emulator Farm</h1>
          <p className="text-gray-500 text-sm mt-1">Android Device Management</p>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="card space-y-4">
          <h2 className="text-lg font-semibold text-gray-100 mb-2">Sign in to your account</h2>
          {import.meta.env.DEV && (
            <p className="text-xs text-amber-200/90 bg-amber-950/40 border border-amber-800/50 rounded-lg px-3 py-2 leading-relaxed">
              <span className="font-medium text-amber-100">Local dev</span> — first field is{' '}
              <span className="font-mono text-amber-50">username</span> (e.g.{' '}
              <span className="font-mono">dev</span>), second is{' '}
              <span className="font-mono text-amber-50">password</span> (e.g.{' '}
              <span className="font-mono">devlocal123</span>). Do not swap them.
            </p>
          )}

          {error && (
            <div className="flex items-center gap-2 text-red-400 bg-red-900/20 border border-red-800 rounded-lg px-3 py-2 text-sm">
              <AlertCircle className="w-4 h-4 flex-shrink-0" />
              {error}
            </div>
          )}

          <div>
            <label className="label">Username (not password)</label>
            <input
              type="text"
              name="username"
              className="input"
              placeholder="dev"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoFocus
              autoComplete="username"
            />
          </div>

          <div>
            <label className="label">Password</label>
            <input
              type="password"
              name="password"
              className="input"
              placeholder={import.meta.env.DEV ? 'devlocal123' : '••••••••'}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
            />
          </div>

          <button
            type="submit"
            disabled={loading}
            className="btn-primary w-full justify-center py-2.5 mt-2"
          >
            {loading && <Loader2 className="w-4 h-4 animate-spin" />}
            {loading ? 'Signing in...' : 'Sign in'}
          </button>
        </form>

        <p className="text-center text-gray-600 text-xs mt-6">
          Android Emulator Farm v1.0.0
        </p>
      </div>
    </div>
  )
}
