'use client'

import Link from 'next/link'

import { MetricTile } from './MetricTile'
import { StatusBadge } from './StatusBadge'
import type { Device } from '@/lib/types'
import {
  deviceAccent,
  formatPercent,
  formatRelativeTime,
  formatSpeed,
  formatTemperature,
  temperatureLevel,
  usageLevel,
} from '@/lib/utils'

export interface DeviceCardProps {
  device: Device
}

/** Summary card for one PC: status plus the headline CPU/GPU/RAM/temp readings. */
export function DeviceCard({ device }: DeviceCardProps) {
  const metrics = device.metrics
  const accent = deviceAccent(device.deviceId)

  return (
    <Link href={`/dashboard/devices/${device.deviceId}`} data-testid="device-card">
      <article className="card card--interactive" style={{ borderTopColor: accent }}>
        <div className="device-card__header">
          <div>
            <h3 className="device-card__name">{device.name}</h3>
            <span className="device-card__id">{device.deviceId}</span>
          </div>
          <StatusBadge online={device.online} status={device.status} />
        </div>

        <div className="device-card__metrics">
          <MetricTile label="CPU" value={formatPercent(metrics?.cpuUsage)} level={usageLevel(metrics?.cpuUsage)} />
          <MetricTile label="GPU" value={formatPercent(metrics?.gpuUsage)} level={usageLevel(metrics?.gpuUsage)} />
          <MetricTile label="RAM" value={formatPercent(metrics?.ramUsage)} level={usageLevel(metrics?.ramUsage)} />
          <MetricTile
            label="Temp"
            value={formatTemperature(metrics?.cpuTemperature)}
            level={temperatureLevel(metrics?.cpuTemperature)}
          />
          <MetricTile label="Download" value={formatSpeed(metrics?.downloadMbps)} level="unknown" />
          <MetricTile label="Upload" value={formatSpeed(metrics?.uploadMbps)} level="unknown" />
        </div>

        <div className="device-card__footer">
          <span>{device.os ?? 'Unknown OS'}</span>
          <span>{device.online ? `Updated ${formatRelativeTime(metrics?.timestamp)}` : `Last seen ${formatRelativeTime(device.lastSeen)}`}</span>
        </div>
      </article>
    </Link>
  )
}

export default DeviceCard