'use client'

import { cn } from '@/lib/utils'

export interface MetricTileProps {
  label: string
  value: string
  level?: 'ok' | 'warn' | 'critical' | 'unknown'
  hint?: string
}

/** One labelled reading (CPU 42%, TEMP 55 °C, ...). */
export function MetricTile({ label, value, level = 'ok', hint }: MetricTileProps) {
  return (
    <div className="metric" data-testid={`metric-${label.toLowerCase()}`}>
      <span className="metric__label">{label}</span>
      <span className={cn('metric__value', `metric__value--${level}`)}>{value}</span>
      {hint ? <span className="small muted">{hint}</span> : null}
    </div>
  )
}

export interface StatCardProps {
  label: string
  value: string | number
  hint?: string
}

/** Larger summary tile used in the dashboard header strip. */
export function StatCard({ label, value, hint }: StatCardProps) {
  return (
    <div className="stat">
      <div className="stat__label">{label}</div>
      <div className="stat__value">{value}</div>
      {hint ? <div className="stat__hint">{hint}</div> : null}
    </div>
  )
}

export default MetricTile