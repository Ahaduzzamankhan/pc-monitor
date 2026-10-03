'use client'

import { DeviceCard } from './DeviceCard'
import { EmptyState, ErrorState, LoadingState } from './States'
import type { Device } from '@/lib/types'

export interface DeviceGridProps {
  devices: Device[] | null
  loading?: boolean
  error?: Error | null
  onRetry?: () => void
}

/** Responsive grid of {@link DeviceCard}s with loading/empty/error handling. */
export function DeviceGrid({ devices, loading, error, onRetry }: DeviceGridProps) {
  if (loading && !devices) return <LoadingState label="Loading devices…" />
  if (error && !devices) {
    return (
      <ErrorState
        title="Cannot load devices"
        message={error.message}
        onRetry={onRetry}
      />
    )
  }
  if (!devices || devices.length === 0) {
    return (
      <EmptyState
        title="No PCs registered yet"
        description="Install PC-Monitor.exe on a PC - it registers itself and appears here automatically."
      />
    )
  }

  return (
    <div className="device-grid" data-testid="device-grid">
      {devices.map((device) => (
        <DeviceCard key={device.deviceId} device={device} />
      ))}
    </div>
  )
}

export default DeviceGrid