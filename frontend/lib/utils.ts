/** Presentation helpers: local-time formatting, units, and class names. */

export function cn(...values: Array<string | false | null | undefined>): string {
  return values.filter(Boolean).join(' ')
}

export function isNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}

/** Parse an ISO-8601 UTC timestamp; returns `null` for missing/invalid input. */
export function parseTimestamp(value: string | null | undefined): Date | null {
  if (!value) return null
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? null : date
}

/** Absolute local time, e.g. `3 Oct 2026, 14:32:05`. */
export function formatLocalDateTime(value: string | null | undefined): string {
  const date = parseTimestamp(value)
  if (!date) return '—'
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium',
    timeStyle: 'medium',
  }).format(date)
}

/** Short local time, e.g. `14:32:05`. */
export function formatLocalTime(value: string | null | undefined): string {
  const date = parseTimestamp(value)
  if (!date) return '—'
  return new Intl.DateTimeFormat(undefined, { timeStyle: 'medium' }).format(date)
}

/** Axis-friendly stamp that adapts to the selected range. */
export function formatAxisTime(value: string | null | undefined, rangeHours = 6): string {
  const date = parseTimestamp(value)
  if (!date) return ''
  const includeDate = rangeHours > 24
  return new Intl.DateTimeFormat(undefined, {
    month: includeDate ? 'short' : undefined,
    day: includeDate ? 'numeric' : undefined,
    hour: '2-digit',
    minute: '2-digit',
    ...(rangeHours <= 6 ? { second: undefined } : {}),
  }).format(date)
}

/** `14 minutes ago`, `just now`, `in 2 minutes`. */
export function formatRelativeTime(value: string | number | null | undefined): string {
  const date =
    typeof value === 'number' ? new Date(Date.now() - value * 1000) : parseTimestamp(value)
  if (!date) return 'unknown'

  const deltaSeconds = Math.round((Date.now() - date.getTime()) / 1000)
  const absolute = Math.abs(deltaSeconds)
  const units: Array<[Intl.RelativeTimeFormatUnit, number]> = [
    ['second', 60],
    ['minute', 60],
    ['hour', 24],
    ['day', 7],
  ]

  if (absolute < 10) return 'just now'
  let amount = deltaSeconds
  let unit: Intl.RelativeTimeFormatUnit = 'second'
  let divisor = 1
  if (absolute >= 60) {
    amount = Math.round(deltaSeconds / 60)
    unit = 'minute'
    divisor = 60
  }
  if (absolute >= 3600) {
    amount = Math.round(deltaSeconds / 3600)
    unit = 'hour'
  }
  if (absolute >= 86400) {
    amount = Math.round(deltaSeconds / 86400)
    unit = 'day'
  }
  const formatter = new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' })
  void divisor
  void units
  return formatter.format(-amount, unit)
}

/** `55 °C` or `—` when the sensor is unavailable. */
export function formatTemperature(value: number | null | undefined, unit = '°C'): string {
  return isNumber(value) ? `${Math.round(value)}${unit}` : '—'
}

/** `42%` or `—`. */
export function formatPercent(value: number | null | undefined): string {
  return isNumber(value) ? `${Math.round(value)}%` : '—'
}

/** Speed formatting for MB/s values (auto-scales to Mb/s when needed). */
export function formatSpeed(value: number | null | undefined, unit = 'Mbps'): string {
  if (!isNumber(value)) return '—'
  if (value < 0.01) return `0 ${unit}`
  if (value < 10) return `${value.toFixed(2)} ${unit}`
  return `${value.toFixed(1)} ${unit}`
}

/** `8.1 GB` from megabytes. */
export function formatMegabytes(value: number | null | undefined): string {
  if (!isNumber(value)) return '—'
  return `${(value / 1024).toFixed(1)} GB`
}

/** Severity band used for colours: `ok` | `warn` | `critical` | `unknown`. */
export function usageLevel(value: number | null | undefined): 'ok' | 'warn' | 'critical' | 'unknown' {
  if (!isNumber(value)) return 'unknown'
  if (value >= 90) return 'critical'
  if (value >= 75) return 'warn'
  return 'ok'
}

export function temperatureLevel(
  value: number | null | undefined,
): 'ok' | 'warn' | 'critical' | 'unknown' {
  if (!isNumber(value)) return 'unknown'
  if (value >= 85) return 'critical'
  if (value >= 70) return 'warn'
  return 'ok'
}

/** Deterministic accent colour per device so cards stay distinguishable. */
export function deviceAccent(deviceId: string): string {
  const palette = ['#38bdf8', '#a78bfa', '#34d399', '#fbbf24', '#f472b6', '#60a5fa']
  let hash = 0
  for (let index = 0; index < deviceId.length; index += 1) {
    hash = (hash * 31 + deviceId.charCodeAt(index)) % palette.length
  }
  return palette[hash]
}