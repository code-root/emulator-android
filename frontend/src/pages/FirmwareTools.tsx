import { ArrowLeft } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import FirmwareManager from '../components/FirmwareManager'

export default function FirmwareTools() {
  const navigate = useNavigate()

  return (
    <div className="p-6 mx-auto max-w-6xl">
      {/* Header */}
      <div className="flex items-center gap-3 mb-6">
        <button onClick={() => navigate('/devices')} className="btn-secondary btn-sm">
          <ArrowLeft className="w-4 h-4" />
        </button>
        <div>
          <h1 className="text-2xl font-bold text-gray-100">Firmware Manager</h1>
          <p className="text-gray-400 text-sm mt-1">Download and verify Samsung firmware</p>
        </div>
      </div>

      {/* Manager */}
      <FirmwareManager />
    </div>
  )
}
