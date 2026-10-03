/**
 * Types mirroring the FastAPI responses.
 *
 * Every timestamp is ISO-8601 **UTC**; the dashboard converts to the viewer's
 * local time in `lib/utils.ts`.
 */

export type DeviceStatus = 'online' | 'offline'

export type HistoryRange = '1h' | '6h' | '24h' | '7d'

export const HISTORY_RANGES: HistoryRange[] = ['1h', '6h', '24h', '7d']

export interface TelemetrySummary {
  timestamp: string | null
  cpuUsage: number | null
  gpuUsage: number | null
  ramUsage: number | null
  cpuTemperature: number | null
  gpuTemperature: number | null
  diskUsage: number | null
  downloadMbps: number | null
  uploadMbps: number | null
  batteryPercent: number | null
}

export interface Device {
  deviceId: string
  name: string
  online: boolean
  status: DeviceStatus
  lastSeen: string | null
  secondsSinceLastSeen: number | null
  createdAt: string | null
  agentVersion: string | null
  os: string | null
  architecture: string | null
  hostname: string | null
  cpuModel: string | null
  gpuModel: string | null
  ramTotalMB: number | null
  diskTotalGB: number | null
  telemetryIntervalSeconds: number | null
  startupEnabled: boolean | null
  telemetryCount?: number | null
  metrics: TelemetrySummary | null
}

export interface DeviceListResponse {
  devices: Device[]
  count: number
  onlineCount: number
  generatedAt: string
  refreshAfterSeconds: number
}

export interface LogEntry {
  logId: string | null
  deviceId: string | null
  deviceName: string | null
  event: string
  level: 'info' | 'warning' | 'error' | string
  message: string
  data: Record<string, unknown>
  timestamp: string | null
}

export interface LogListResponse {
  logs: LogEntry[]
  count: number
  generatedAt: string
}

export interface DeviceDetail extends Device {
  telemetryStored: number
  retentionDays: number
  retentionHours: number
  supportedRanges: HistoryRange[]
  recentLogs: LogEntry[]
}

export interface TelemetryPoint {
  timestamp: string
  cpuUsage: number | null
  gpuUsage: number | null
  ramUsage: number | null
  cpuTemperature: number | null
  gpuTemperature: number | null
  diskUsage: number | null
  downloadMbps: number | null
  uploadMbps: number | null
  diskReadMbps: number | null
  diskWriteMbps: number | null
}

export interface TelemetrySeries {
  deviceId: string
  range: HistoryRange
  rangeHours: number
  startTime: string
  endTime: string
  resolutionSeconds: number
  count: number
  empty: boolean
  truncated: boolean
  maxPoints: number
  retentionDays: number
  points: TelemetryPoint[]
}

export interface DeviceSettingsUpdate {
  name?: string
  telemetryIntervalSeconds?: number
  startupEnabled?: boolean
}

export interface ApiMeta {
  name: string
  version: string
  environment: string
  retentionDays: number
  supportedRanges: HistoryRange[]
  telemetryIntervalSeconds: number
  heartbeatIntervalSeconds: number
  onlineThresholdSeconds: number
  maxTelemetryPoints: number
}

export interface HealthStatus {
  status: string
  version: string
  environment: string
  database: string
  time: string
  uptimeSeconds: number
  retentionDays: number
  onlineThresholdSeconds: number
}

export interface CleanupStatus {
  enabled: boolean
  retentionDays: number
  ttlPolicy: Record<string, unknown>
  lastRunAt: string | null
  lastRunResult: Record<string, unknown> | null
  totalErrors: number
}