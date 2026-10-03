'use client'

import { useMemo, useState } from 'react'

import { DeviceGrid } from './DeviceGrid'
import { Navbar } from './Navbar'
import { usePolling } from '@/hooks/usePolling'
import { getDevices, REFRESH_SECONDS } from '@/lib/api'

/** All devices with a client-side filter for quick lookup. */
export function DevicesListView() {
  const [filter, setFilter] = useState('')
  const { data, error, loading, refreshing, lastUpdated, refresh } = usePolling(
    getDevices,
    REFRESH_SECONDS,
  )

  const devices = useMemo(() => {
    const all = data?.devices ?? []
    const needle = filter.trim().toLowerCase()
    if (!needle) return all
    return all.filter(
      (device) =>
        device.name.toLowerCase().includes(needle) ||
        device.deviceId.toLowerCase().includes(needle) ||
        (device.os ?? '').toLowerCase().includes(needle),
    )
  }, [data, filter])

  return (
    <>
      <Navbar
        title="Devices"
        subtitle="Every PC that has registered its agent"
        onlineCount={data?.onlineCount}
        totalCount={data?.count}
        lastUpdated={lastUpdated}
        refreshing={refreshing}
        actions={
          <button type="button" className="button" onClick={() => void refresh()}>
            Refresh
          </button>
        }
      />

      <div className="content">
        <div className="row">
          <input
            className="field__input"
            style={{ maxWidth: 320 }}
            placeholder="Filter by name, id or OS…"
            value={filter}
            onChange={(event) => setFilter(event.target.value)}
            aria-label="Filter devices"
          />
          <span className="small muted">
            {devices.length} shown · auto-refresh every {REFRESH_SECONDS}s
          </span>
        </div>

        <DeviceGrid devices={devices} loading={loading} error={error} onRetry={() => void refresh()} />
      </div>
    </>
  )
}

export default DevicesListView