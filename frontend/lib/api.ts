/**
 * Typed API client for the PC Monitor backend.
 *
 * Only `NEXT_PUBLIC_API_URL` (the backend URL) is public - no Firebase Admin
 * credentials or other secrets ever reach the browser. Requests go straight to
 * the FastAPI service, which talks to Firestore server side.
 */

import type {
  ApiMeta,
  CleanupStatus,
  Device,
  DeviceDetail,
  DeviceListResponse,
  DeviceSettingsUpdate,
  HealthStatus,
  HistoryRange,
  LogEntry,
  LogListResponse,
  TelemetrySeries,
} from './types'

export const API_URL: string = (
  process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'
).replace(/\/+$/, '')

/** Dashboard auto-refresh cadence (seconds). Kept polite on purpose. */
export const REFRESH_SECONDS: number = Number(
  process.env.NEXT_PUBLIC_REFRESH_SECONDS ?? '15',
)

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly details?: unknown

  constructor(status: number, code: string, message: string, details?: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.details = details
  }

  /** Message suitable for showing to a human. */
  get friendlyMessage(): string {
    if (this.status === 0) return 'Cannot reach the PC Monitor API.'
    if (this.status === 404) return 'Not found.'
    if (this.status >= 500) return 'The PC Monitor API reported an internal error.'
    return this.message
  }
}

interface ErrorEnvelope {
  error?: { code?: string; message?: string; details?: unknown }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${API_URL}${path}`, {
      cache: 'no-store',
      headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
      ...init,
    })
  } catch (error) {
    // Network failure, DNS error, CORS rejection, offline browser...
    throw new ApiError(0, 'network_error', (error as Error).message)
  }

  if (response.status === 204) return undefined as T

  const text = await response.text()
  let body: unknown = null
  if (text) {
    try {
      body = JSON.parse(text)
    } catch {
      body = null
    }
  }

  if (!response.ok) {
    const envelope = (body ?? {}) as ErrorEnvelope
    throw new ApiError(
      response.status,
      envelope.error?.code ?? `http_${response.status}`,
      envelope.error?.message ?? `Request failed with status ${response.status}`,
      envelope.error?.details,
    )
  }

  return body as T
}

// ---------------------------------------------------------------------------
// Devices
// ---------------------------------------------------------------------------

/** Every registered PC. Devices appear here automatically on registration. */
export async function getDevices(): Promise<DeviceListResponse> {
  return request<DeviceListResponse>('/api/devices')
}

/** Full detail for one device (hardware, retention info, recent activity). */
export async function getDevice(deviceId: string): Promise<DeviceDetail> {
  return request<DeviceDetail>(`/api/devices/${encodeURIComponent(deviceId)}`)
}

/** Telemetry history. Only the selected window is fetched; max 7 days. */
export async function getTelemetry(
  deviceId: string,
  range: HistoryRange = '6h',
): Promise<TelemetrySeries> {
  const query = new URLSearchParams({ range })
  return request<TelemetrySeries>(
    `/api/devices/${encodeURIComponent(deviceId)}/telemetry?${query.toString()}`,
  )
}

/** Rename a device / change interval / record the startup preference. */
export async function updateDevice(
  deviceId: string,
  update: DeviceSettingsUpdate,
): Promise<Device> {
  return request<Device>(`/api/devices/${encodeURIComponent(deviceId)}`, {
    method: 'PATCH',
    body: JSON.stringify(update),
  })
}

/**
 * Remove a device. Telemetry is purged and the agent token is revoked, so the
 * old executable must register again to reconnect.
 */
export async function deleteDevice(deviceId: string): Promise<{
  deviceId: string
  deleted: boolean
  tokenRevoked: boolean
  deletedTelemetry: number | null
  message: string
}> {
  return request(`/api/devices/${encodeURIComponent(deviceId)}`, { method: 'DELETE' })
}

// ---------------------------------------------------------------------------
// Logs
// ---------------------------------------------------------------------------
export async function getDeviceLogs(deviceId: string, limit = 100): Promise<LogEntry[]> {
  const query = new URLSearchParams({ limit: String(limit) })
  const response = await request<LogListResponse>(
    `/api/devices/${encodeURIComponent(deviceId)}/logs?${query.toString()}`,
  )
  return response.logs
}

export async function getLogs(
  options: { limit?: number; deviceId?: string; level?: string } = {},
): Promise<LogEntry[]> {
  const query = new URLSearchParams()
  if (options.limit) query.set('limit', String(options.limit))
  if (options.deviceId) query.set('deviceId', options.deviceId)
  if (options.level) query.set('level', options.level)
  const suffix = query.toString() ? `?${query.toString()}` : ''
  const response = await request<LogListResponse>(`/api/logs${suffix}`)
  return response.logs
}

// ---------------------------------------------------------------------------
// System
// ---------------------------------------------------------------------------
export async function getMeta(): Promise<ApiMeta> {
  return request<ApiMeta>('/api/meta')
}

export async function getHealth(): Promise<HealthStatus> {
  return request<HealthStatus>('/health')
}

export async function getCleanupStatus(): Promise<CleanupStatus> {
  return request<CleanupStatus>('/api/system/cleanup')
}