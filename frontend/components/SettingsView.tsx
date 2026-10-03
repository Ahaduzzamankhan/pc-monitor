'use client'

import Link from 'next/link'
import { useState } from 'react'

import { Navbar } from './Navbar'
import { StatusBadge } from './StatusBadge'
import { EmptyState, ErrorState, LoadingState } from './States'
import { usePolling } from '@/hooks/usePolling'
import { REFRESH_SECONDS, deleteDevice, getDevices, getMeta, updateDevice } from '@/lib/api'
import { formatLocalDateTime, formatRelativeTime } from '@/lib/utils'

const INTERVAL_OPTIONS = [10, 15, 30, 60, 120, 300]

/** Per-device settings: name, sampling interval, startup preference, removal. */
export function SettingsView() {
  const devices = usePolling(getDevices, REFRESH_SECONDS * 4)
  const meta = usePolling(getMeta, REFRESH_SECONDS * 12)
  const [message, setMessage] = useState<{ deviceId: string; text: string; tone: 'ok' | 'error' } | null>(
    null,
  )
  const [busyId, setBusyId] = useState<string | null>(null)

  async function rename(deviceId: string, name: string) {
    setBusyId(deviceId)
    setMessage(null)
    try {
      await updateDevice(deviceId, { name })
      setMessage({ deviceId, text: 'Saved.', tone: 'ok' })
      await devices.refresh()
    } catch (error) {
      setMessage({ deviceId, text: (error as Error).message, tone: 'error' })
    } finally {
      setBusyId(null)
    }
  }

  async function setInterval(deviceId: string, seconds: number) {
    setBusyId(deviceId)
    setMessage(null)
    try {
      await updateDevice(deviceId, { telemetryIntervalSeconds: seconds })
      setMessage({ deviceId, text: 'Interval updated.', tone: 'ok' })
      await devices.refresh()
    } catch (error) {
      setMessage({ deviceId, text: (error as Error).message, tone: 'error' })
    } finally {
      setBusyId(null)
    }
  }

  async function setStartup(deviceId: string, enabled: boolean) {
    setBusyId(deviceId)
    setMessage(null)
    try {
      await updateDevice(deviceId, { startupEnabled: enabled })
      setMessage({ deviceId, text: 'Startup preference saved.', tone: 'ok' })
      await devices.refresh()
    } catch (error) {
      setMessage({ deviceId, text: (error as Error).message, tone: 'error' })
    } finally {
      setBusyId(null)
    }
  }

  async function remove(deviceId: string) {
    const confirmed =
      typeof window === 'undefined'
        ? true
        : window.confirm(
            `Remove ${deviceId}? Its telemetry is deleted and the agent token is revoked - the PC must register again.`,
          )
    if (!confirmed) return

    setBusyId(deviceId)
    setMessage(null)
    try {
      const result = await deleteDevice(deviceId)
      setMessage({ deviceId, text: result.message, tone: 'ok' })
      await devices.refresh()
    } catch (error) {
      setMessage({ deviceId, text: (error as Error).message, tone: 'error' })
    } finally {
      setBusyId(null)
    }
  }

  return (
    <>
      <Navbar
        title="Settings"
        subtitle="Device preferences and retention"
        lastUpdated={devices.lastUpdated}
        refreshing={devices.refreshing}
        actions={
          <button type="button" className="button" onClick={() => void devices.refresh()}>
            Refresh
          </button>
        }
      />

      <div className="content">
        <section className="card">
          <h3 style={{ marginTop: 0 }}>Retention</h3>
          <div className="detail-grid">
            <div className="detail-item">
              <div className="detail-item__label">History kept</div>
              <div className="detail-item__value">
                {meta.data?.retentionDays ?? 7} days
              </div>
            </div>
            <div className="detail-item">
              <div className="detail-item__label">Ranges</div>
              <div className="detail-item__value">
                {(meta.data?.supportedRanges ?? ['1h', '6h', '24h', '7d']).join(' · ')}
              </div>
            </div>
            <div className="detail-item">
              <div className="detail-item__label">Online threshold</div>
              <div className="detail-item__value">
                {meta.data?.onlineThresholdSeconds ?? 120} seconds
              </div>
            </div>
            <div className="detail-item">
              <div className="detail-item__label">API version</div>
              <div className="detail-item__value">{meta.data?.version ?? '—'}</div>
            </div>
          </div>
          <p className="small muted" style={{ marginBottom: 0 }}>
            Telemetry expires automatically via Firestore TTL on <code>expiresAt</code>; the backend
            cleanup job is the fallback. Device registrations never expire.
          </p>
        </section>

        {devices.loading && !devices.data ? (
          <LoadingState label="Loading devices…" />
        ) : devices.error && !devices.data ? (
          <ErrorState
            title="Cannot load devices"
            message={devices.error.message}
            onRetry={() => void devices.refresh()}
          />
        ) : !devices.data || devices.data.devices.length === 0 ? (
          <EmptyState
            title="No devices yet"
            description="Install PC-Monitor.exe on a PC to get started."
          />
        ) : (
          <div className="stack">
            {devices.data.devices.map((device) => (
              <section className="card" key={device.deviceId} data-testid="settings-device">
                <div className="row row--between">
                  <div className="row">
                    <Link href={`/dashboard/devices/${device.deviceId}`}>
                      <strong>{device.name}</strong>
                    </Link>
                    <span className="code">{device.deviceId}</span>
                    <StatusBadge online={device.online} status={device.status} pulse={false} />
                  </div>
                  <span className="small muted">
                    Agent {device.agentVersion ?? '—'} · last seen {formatRelativeTime(device.lastSeen)}
                  </span>
                </div>

                <div className="row" style={{ marginTop: 14, alignItems: 'flex-end' }}>
                  <label className="field" style={{ marginBottom: 0, minWidth: 220 }}>
                    <span className="field__label">Device name</span>
                    <input
                      className="field__input"
                      defaultValue={device.name}
                      key={`${device.deviceId}-${device.name}`}
                      onBlur={(event) => {
                        if (event.target.value !== device.name) {
                          void rename(device.deviceId, event.target.value)
                        }
                      }}
                      aria-label={`Name for ${device.name}`}
                    />
                  </label>

                  <label className="field" style={{ marginBottom: 0 }}>
                    <span className="field__label">Telemetry interval</span>
                    <select
                      className="field__select"
                      value={device.telemetryIntervalSeconds ?? 30}
                      onChange={(event) => void setInterval(device.deviceId, Number(event.target.value))}
                      aria-label={`Interval for ${device.name}`}
                    >
                      {INTERVAL_OPTIONS.map((option) => (
                        <option key={option} value={option}>
                          {option} seconds
                        </option>
                      ))}
                    </select>
                  </label>

                  <label className="field" style={{ marginBottom: 0 }}>
                    <span className="field__label">Start with Windows</span>
                    <select
                      className="field__select"
                      value={device.startupEnabled ? 'yes' : 'no'}
                      onChange={(event) =>
                        void setStartup(device.deviceId, event.target.value === 'yes')
                      }
                      aria-label={`Startup preference for ${device.name}`}
                    >
                      <option value="yes">Enabled</option>
                      <option value="no">Disabled</option>
                    </select>
                    <span className="field__hint">
                      Stored per device; the agent also has --enable-startup / --no-startup.
                    </span>
                  </label>

                  <button
                    type="button"
                    className="button button--danger"
                    disabled={busyId === device.deviceId}
                    onClick={() => void remove(device.deviceId)}
                  >
                    Remove device
                  </button>
                </div>

                {message?.deviceId === device.deviceId ? (
                  <p className={message.tone === 'error' ? 'level--error' : 'muted'} style={{ marginBottom: 0 }}>
                    {message.text}
                  </p>
                ) : null}

                <p className="small muted" style={{ marginBottom: 0 }}>
                  Registered {formatLocalDateTime(device.createdAt)} · {device.os ?? 'Unknown OS'}
                </p>
              </section>
            ))}
          </div>
        )}
      </div>
    </>
  )
}

export default SettingsView