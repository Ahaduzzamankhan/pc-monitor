'use client'

import { useMemo, useState } from 'react'

import { Navbar } from './Navbar'
import { EmptyState, ErrorState, LoadingState } from './States'
import { usePolling } from '@/hooks/usePolling'
import { getDevices, getLogs, REFRESH_SECONDS } from '@/lib/api'
import { formatLocalDateTime } from '@/lib/utils'

type LevelFilter = 'all' | 'info' | 'warning' | 'error'

/** Fleet-wide activity feed (registration, heartbeats, sensors, errors). */
export function LogsView() {
  const [level, setLevel] = useState<LevelFilter>('all')
  const [deviceId, setDeviceId] = useState<string>('')

  const devices = usePolling(getDevices, REFRESH_SECONDS * 4)
  const logs = usePolling(
    () =>
      getLogs({
        limit: 200,
        deviceId: deviceId || undefined,
        level: level === 'all' ? undefined : level,
      }),
    REFRESH_SECONDS,
    { deps: [level, deviceId] },
  )

  const rows = useMemo(() => logs.data ?? [], [logs.data])

  return (
    <>
      <Navbar
        title="Activity"
        subtitle="Registration, heartbeats, telemetry, sensor and API events"
        lastUpdated={logs.lastUpdated}
        refreshing={logs.refreshing}
        actions={
          <button type="button" className="button" onClick={() => void logs.refresh()}>
            Refresh
          </button>
        }
      />

      <div className="content">
        <div className="row">
          <select
            className="field__select"
            value={deviceId}
            onChange={(event) => setDeviceId(event.target.value)}
            aria-label="Filter by device"
          >
            <option value="">All devices</option>
            {(devices.data?.devices ?? []).map((device) => (
              <option key={device.deviceId} value={device.deviceId}>
                {device.name} ({device.deviceId})
              </option>
            ))}
          </select>

          <select
            className="field__select"
            value={level}
            onChange={(event) => setLevel(event.target.value as LevelFilter)}
            aria-label="Filter by level"
          >
            <option value="all">All levels</option>
            <option value="info">Info</option>
            <option value="warning">Warnings</option>
            <option value="error">Errors</option>
          </select>

          <span className="small muted">Logs never contain tokens or credentials.</span>
        </div>

        {logs.loading && !logs.data ? (
          <LoadingState label="Loading activity…" />
        ) : logs.error && !logs.data ? (
          <ErrorState
            title="Cannot load activity"
            message={logs.error.message}
            onRetry={() => void logs.refresh()}
          />
        ) : rows.length === 0 ? (
          <EmptyState title="No activity yet" description="Events appear once an agent registers." />
        ) : (
          <section className="card">
            <table className="table">
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Device</th>
                  <th>Level</th>
                  <th>Event</th>
                  <th>Detail</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((entry) => (
                  <tr key={entry.logId ?? `${entry.event}-${entry.timestamp}`}>
                    <td className="muted">{formatLocalDateTime(entry.timestamp)}</td>
                    <td>{entry.deviceName ?? entry.deviceId ?? '—'}</td>
                    <td className={`level--${entry.level}`}>{entry.level}</td>
                    <td>{entry.event}</td>
                    <td className="muted">{entry.message}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        )}
      </div>
    </>
  )
}

export default LogsView