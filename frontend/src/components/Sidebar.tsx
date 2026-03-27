import { useState } from 'react'
import { NavLink, useNavigate } from 'react-router-dom'
import { Smartphone, LayoutDashboard, Cpu, Settings, LogOut, ChevronLeft, ChevronRight, Package, Download } from 'lucide-react'
import { useAuthStore } from '../store/auth'
import clsx from 'clsx'

const NAV_ITEMS = [
  { to: '/dashboard', label: 'Dashboard', icon: <LayoutDashboard className="w-5 h-5" /> },
  { to: '/devices', label: 'Devices', icon: <Cpu className="w-5 h-5" /> },
  { to: '/firmware', label: 'Firmware', icon: <Download className="w-5 h-5" /> },
  { to: '/store', label: 'App Store', icon: <Package className="w-5 h-5" /> },
  { to: '/settings', label: 'Settings', icon: <Settings className="w-5 h-5" /> },
]

export default function Sidebar() {
  const [collapsed, setCollapsed] = useState(false)
  const navigate = useNavigate()
  const { user, logout } = useAuthStore()

  function handleLogout() {
    logout()
    navigate('/login', { replace: true })
  }

  return (
    <aside
      className={clsx(
        'flex flex-col bg-gray-900 border-r border-gray-800 transition-all duration-300 shrink-0',
        collapsed ? 'w-16' : 'w-56'
      )}
    >
      {/* Logo */}
      <div className={clsx('flex items-center gap-3 px-4 py-5 border-b border-gray-800', collapsed && 'justify-center px-0')}>
        <div className="w-8 h-8 bg-blue-600 rounded-lg flex items-center justify-center shrink-0">
          <Smartphone className="w-4 h-4 text-white" />
        </div>
        {!collapsed && (
          <div className="overflow-hidden">
            <p className="text-sm font-semibold text-gray-100 whitespace-nowrap">Emulator Farm</p>
            <p className="text-xs text-gray-500">v1.0.0</p>
          </div>
        )}
      </div>

      {/* Nav */}
      <nav className="flex-1 px-2 py-4 space-y-1">
        {NAV_ITEMS.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            className={({ isActive }) =>
              clsx(
                'flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors',
                collapsed && 'justify-center',
                isActive
                  ? 'bg-blue-600/20 text-blue-400 border border-blue-800/50'
                  : 'text-gray-400 hover:text-gray-200 hover:bg-gray-800'
              )
            }
            title={collapsed ? item.label : undefined}
          >
            <span className="shrink-0">{item.icon}</span>
            {!collapsed && <span className="truncate">{item.label}</span>}
          </NavLink>
        ))}
      </nav>

      {/* Bottom section */}
      <div className="border-t border-gray-800 p-2 space-y-1">
        {/* Collapse toggle */}
        <button
          onClick={() => setCollapsed(!collapsed)}
          className={clsx(
            'w-full flex items-center gap-3 px-3 py-2 rounded-lg text-gray-500 hover:text-gray-300 hover:bg-gray-800 text-sm transition-colors',
            collapsed && 'justify-center'
          )}
        >
          {collapsed ? <ChevronRight className="w-4 h-4" /> : <ChevronLeft className="w-4 h-4" />}
          {!collapsed && 'Collapse'}
        </button>

        {/* User info */}
        {user && (
          <div className={clsx('flex items-center gap-2 px-3 py-2 rounded-lg', collapsed && 'justify-center')}>
            <div className="w-7 h-7 rounded-full bg-blue-700 flex items-center justify-center text-xs font-bold text-white shrink-0">
              {user.username[0].toUpperCase()}
            </div>
            {!collapsed && (
              <div className="flex-1 overflow-hidden">
                <p className="text-xs font-medium text-gray-200 truncate">{user.username}</p>
                <p className="text-xs text-gray-500 capitalize">{user.role}</p>
              </div>
            )}
          </div>
        )}

        {/* Logout */}
        <button
          onClick={handleLogout}
          className={clsx(
            'w-full flex items-center gap-3 px-3 py-2 rounded-lg text-gray-500 hover:text-red-400 hover:bg-red-900/20 text-sm transition-colors',
            collapsed && 'justify-center'
          )}
          title={collapsed ? 'Logout' : undefined}
        >
          <LogOut className="w-4 h-4 shrink-0" />
          {!collapsed && 'Logout'}
        </button>
      </div>
    </aside>
  )
}
