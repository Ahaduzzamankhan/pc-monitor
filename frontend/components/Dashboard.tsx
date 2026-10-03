'use client'

import { DeviceGrid } from './DeviceGrid'
import { Navbar } from './Navbar'
import { StatCard } from './MetricTile'
import { usePolling } from '@/hooks/usePolling'
import { getDevices, REFRESH_SECONDS } from '@/lib/api'
import { ApiError } from '@/lib/api'
import { formatRelativeTime } from '@/lib/utils'

/** Overview page: fleet summary plus a card per registered PC. */
export function Dashboard() {
  const { data, error, loading, refreshing, lastUpdated, refresh } = usePolling(
    getDevices,
    REFRESH_SECONDS,
  )

  const devices = data?.devices ?? null
  const online = data?.onlineCount ?? 0
  const total = data?.count ?? 0

  return (
    <>
      <Navbar
        title="PC Monitor"
        subtitle="Live hardware telemetry for every registered PC"
        onlineCount={online}
        totalCount={total}
        lastUpdated={lastUpdated}
        refreshing={refreshing}
        actions={
          <button type="button" className="button" onClick={() => void refresh()}>
            Refresh
          </button>
        }
      />

      <div className="content">
        {error ? (
          <div className="banner banner--warning">
            {error instanceof ApiError ? error.friendlyMessage : 'The PC Monitor API is unreachable.'}{' '}
            Retrying automatically every {REFRESH_SECONDS}s.
          </div>
        ) : null}

        <div className="stat-strip">
          <StatCard label="Registered PCs" value={total} hint="Automatically discovered" />
          <StatCard label="Online" value={online} hint={`Offline threshold ${120}s`} />
          <StatCard
            label="Reporting"
            value={devices?.filter((device) => device.metrics?.timestamp).length ?? 0}
            hint="Devices with telemetry"
          />
          <StatCard
            label="Last update"
            value={lastUpdated ? formatRelativeTime(lastUpdated.toISOString()) : '—'}
            hint={`Auto-refresh every ${REFRESH_SECONDS}s`}
          />
        </div>

        <DeviceGrid
          devices={devices}
          loading={loading}
          error={error}
          onRetry={() => void refresh()}
        />
      </div>
    </>
  )
}

export default Dashboard