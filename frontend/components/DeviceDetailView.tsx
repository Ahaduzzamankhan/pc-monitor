'use client'

import { useCallback, useState } from 'react'

import { CpuChart } from './CpuChart'
import { DeviceHeader } from './DeviceHeader'
import { DiskChart } from './DiskChart'
import { GpuChart } from './GpuChart'
import { MemoryChart } from './MemoryChart'
import { Navbar } from './Navbar'
import { NetworkChart } from './NetworkChart'
import { RangeSelector } from './RangeSelector'
import { TemperatureChart } from './TemperatureChart'
import { EmptyState, ErrorState, LoadingState } from './States'
import { usePolling } from '@/hooks/usePolling'
import { getDevice, getDeviceLogs, getTelemetry, REFRESH_SECONDS } from '@/lib/api'
import { ApiError } from '@/lib/api'
import type { HistoryRange } from '@/lib/types'
import { formatLocalTime } from '@/lib/utils'

export interface DeviceDetailViewProps {
  deviceId: string
}

/**
 * Dynamic device page (`/dashboard/devices/[deviceId]`).
 * Charts fetch only the selected range and refresh on the same polite cadence.
 */
export function DeviceDetailView({ deviceId }: DeviceDetailViewProps) {
  const [range, setRange] = useState<HistoryRange>('6h')

  const device = usePolling(() => getDevice(deviceId), REFRESH_SECONDS, {
    deps: [deviceId],
  })
  const series = usePolling(
    () => getTelemetry(deviceId, range),
    REFRESH_SECONDS,
    { deps: [deviceId, range] },
  )
  const logs = usePolling(() => getDeviceLogs(deviceId, 20), REFRESH_SECONDS, {
    deps: [deviceId],
  })

  const handleRange = useCallback((next: HistoryRange) => setRange(next), [])
  const points = series.data?.points ?? []
  const rangeHours = series.data?.rangeHours ?? 6

  if (device.loading && !device.data) {
    return (
      <>
        <Navbar title={deviceId} subtitle="Loading device…" />
        <div className="content">
          <LoadingState />
        </div>
      </>
    )
  }

  if (device.error && !device.data) {
    return (
      <>
        <Navbar title={deviceId} />
        <div className="content">
          <ErrorState
            title="Cannot load this device"
            message={
              device.error instanceof ApiError
                ? device.error.friendlyMessage
                : 'Unexpected error while loading the device.'
            }
            onRetry={() => void device.refresh()}
          />
        </div>
      </>
    )
  }

  const detail = device.data

  return (
    <>
      <Navbar
        title={detail?.name ?? deviceId}
        subtitle={detail?.os ?? 'Unknown system'}
        onlineCount={detail?.online ? 1 : 0}
        totalCount={1}
        lastUpdated={device.lastUpdated}
        refreshing={device.refreshing}
        actions={
          <button
            type="button"
            className="button"
            onClick={() => {
              void device.refresh()
              void series.refresh()
            }}
          >
            Refresh
          </button>
        }
      />

      <div className="content">
        {detail ? <DeviceHeader device={detail} /> : null}

        <div className="row row--between">
          <h3 style={{ margin: 0 }}>History</h3>
          <RangeSelector
            value={range}
            onChange={handleRange}
            disabled={series.loading && !series.data}
            available={detail?.supportedRanges}
          />
        </div>

        {series.error && !series.data ? (
          <ErrorState
            title="Cannot load telemetry"
            message={
              series.error instanceof ApiError
                ? series.error.friendlyMessage
                : 'Unexpected error while loading telemetry.'
            }
            onRetry={() => void series.refresh()}
          />
        ) : (
          <div className="chart-grid">
            <CpuChart points={points} rangeHours={rangeHours} />
            <GpuChart points={points} rangeHours={rangeHours} gpuName={detail?.gpuModel} />
            <MemoryChart points={points} rangeHours={rangeHours} />
            <TemperatureChart points={points} rangeHours={rangeHours} />
            <DiskChart points={points} rangeHours={rangeHours} />
            <NetworkChart points={points} rangeHours={rangeHours} />
          </div>
        )}

        {series.data ? (
          <p className="small muted">
            {series.data.count} samples · resolution {series.data.resolutionSeconds}s ·{' '}
            {series.data.truncated ? `downsampled to the ${series.data.maxPoints} most recent points` : 'full resolution'} ·
            history is capped at {series.data.retentionDays} days
          </p>
        ) : null}

        <section className="card">
          <h3 style={{ marginTop: 0 }}>Recent activity</h3>
          {!logs.data || logs.data.length === 0 ? (
            <EmptyState title="No activity recorded yet" />
          ) : (
            <table className="table">
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Level</th>
                  <th>Event</th>
                  <th>Detail</th>
                </tr>
              </thead>
              <tbody>
                {logs.data.map((entry) => (
                  <tr key={entry.logId ?? `${entry.event}-${entry.timestamp}`}>
                    <td className="muted">{formatLocalTime(entry.timestamp)}</td>
                    <td className={`level--${entry.level}`}>{entry.level}</td>
                    <td>{entry.event}</td>
                    <td className="muted">{entry.message}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      </div>
    </>
  )
}

export default DeviceDetailView