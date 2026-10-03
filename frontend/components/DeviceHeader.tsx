'use client'

import Link from 'next/link'

import { StatCard } from './MetricTile'
import { StatusBadge } from './StatusBadge'
import type { DeviceDetail } from '@/lib/types'
import {
  formatLocalDateTime,
  formatMegabytes,
  formatPercent,
  formatRelativeTime,
  formatTemperature,
  temperatureLevel,
  usageLevel,
} from '@/lib/utils'

const TEMPERATURE_HINT: Record<string, string> = {
  ok: 'Normal',
  warn: 'Warm',
  critical: 'Hot',
  unknown: 'Sensor unavailable',
}

export interface DeviceHeaderProps {
  device: DeviceDetail
}

/** Full device page header: identity, status, hardware and current metrics. */
export function DeviceHeader({ device }: DeviceHeaderProps) {
  const metrics = device.metrics

  return (
    <div className="stack" data-testid="device-header">
      <div className="card">
        <div className="row row--between">
          <div>
            <div className="row">
              <Link href="/dashboard/devices" className="small muted">
                ← All devices
              </Link>
            </div>
            <h2 style={{ margin: '6px 0 2px' }}>{device.name}</h2>
            <span className="code">{device.deviceId}</span>
          </div>
          <div className="row">
            <StatusBadge online={device.online} status={device.status} />
          </div>
        </div>

        <div className="detail-grid" style={{ marginTop: 16 }}>
          <Detail label="Status" value={device.online ? 'Online' : 'Offline'} />
          <Detail
            label="Last seen"
            value={device.online ? 'Reporting now' : formatRelativeTime(device.lastSeen)}
          />
          <Detail label="Agent version" value={device.agentVersion ?? '—'} />
          <Detail label="Windows" value={device.os ?? '—'} />
          <Detail label="Architecture" value={device.architecture ?? '—'} />
          <Detail label="Hostname" value={device.hostname ?? '—'} />
          <Detail label="CPU" value={device.cpuModel ?? '—'} />
          <Detail label="GPU" value={device.gpuModel ?? 'Not reported'} />
          <Detail label="RAM" value={formatMegabytes(device.ramTotalMB)} />
          <Detail label="Disk" value={device.diskTotalGB ? `${device.diskTotalGB} GB` : '—'} />
          <Detail label="Interval" value={device.telemetryIntervalSeconds ? `${device.telemetryIntervalSeconds}s` : '—'} />
          <Detail label="Registered" value={formatLocalDateTime(device.createdAt)} />
        </div>
      </div>

      <div className="stat-strip">
        <StatCard
          label="CPU"
          value={formatPercent(metrics?.cpuUsage)}
          hint={`${device.cpuModel ?? 'Unknown CPU'}`}
        />
        <StatCard label="GPU" value={formatPercent(metrics?.gpuUsage)} hint={device.gpuModel ?? 'Unavailable'} />
        <StatCard label="RAM" value={formatPercent(metrics?.ramUsage)} hint={formatMegabytes(device.ramTotalMB)} />
        <StatCard
          label="CPU temp"
          value={formatTemperature(metrics?.cpuTemperature)}
          hint={TEMPERATURE_HINT[temperatureLevel(metrics?.cpuTemperature)]}
        />
        <StatCard
          label="GPU temp"
          value={formatTemperature(metrics?.gpuTemperature)}
          hint={TEMPERATURE_HINT[temperatureLevel(metrics?.gpuTemperature)]}
        />
        <StatCard label="Disk" value={formatPercent(metrics?.diskUsage)} hint="System volume" />
        <StatCard
          label="Battery"
          value={formatPercent(metrics?.batteryPercent)}
          hint={metrics?.batteryPercent === null || metrics?.batteryPercent === undefined ? 'No battery' : 'Laptop'}
        />
        <StatCard label="Samples" value={device.telemetryStored} hint={`Last ${device.retentionDays} days kept`} />
      </div>

      <div className="row small muted">
        <span>
          Readings are collected locally on the PC and uploaded every{' '}
          {device.telemetryIntervalSeconds ?? 30}s. CPU load is {usageLevel(metrics?.cpuUsage)}.
        </span>
      </div>
    </div>
  )
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div className="detail-item">
      <div className="detail-item__label">{label}</div>
      <div className="detail-item__value">{value}</div>
    </div>
  )
}

export default DeviceHeader