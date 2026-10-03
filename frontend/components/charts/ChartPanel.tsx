'use client'

import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { EmptyState } from '@/components/States'
import type { TelemetryPoint } from '@/lib/types'
import { formatAxisTime } from '@/lib/utils'

export interface ChartSeries {
  key: keyof TelemetryPoint
  name: string
  color: string
  unit?: string
}

export interface ChartPanelProps {
  title: string
  description?: string
  points: TelemetryPoint[]
  series: ChartSeries[]
  rangeHours: number
  height?: number
  /** Fixed Y axis, e.g. `[0, 100]` for percentages. */
  domain?: [number | 'auto', number | 'auto']
  /** Unit appended to tooltip values. */
  unit?: string
  emptyTitle?: string
  emptyDescription?: string
  testId?: string
}

const AXIS_COLOR = '#64748b'
const GRID_COLOR = 'rgba(148, 163, 184, 0.14)'

/**
 * Reusable line-chart panel shared by every chart component.
 * Renders a friendly empty state instead of an empty canvas.
 */
export function ChartPanel({
  title,
  description,
  points,
  series,
  rangeHours,
  height = 260,
  domain,
  unit,
  emptyTitle = 'No data in this range',
  emptyDescription = 'Telemetry is collected every 30 seconds. Data will appear once the agent uploads a sample.',
  testId,
}: ChartPanelProps) {
  const isEmpty = !points || points.length === 0

  return (
    <section className="card" data-testid={testId} aria-label={title}>
      <header className="chart-card__header">
        <div>
          <h3 className="chart-card__title">{title}</h3>
          {description ? <p className="small muted" style={{ margin: 0 }}>{description}</p> : null}
        </div>
      </header>

      {isEmpty ? (
        <EmptyState title={emptyTitle} description={emptyDescription} />
      ) : (
        <ResponsiveContainer width="100%" height={height}>
          <LineChart data={points} margin={{ top: 8, right: 12, bottom: 4, left: -12 }}>
            <CartesianGrid stroke={GRID_COLOR} strokeDasharray="3 3" vertical={false} />
            <XAxis
              dataKey="timestamp"
              tickFormatter={(value: string) => formatAxisTime(value, rangeHours)}
              stroke={AXIS_COLOR}
              tick={{ fontSize: 11, fill: AXIS_COLOR }}
              minTickGap={48}
            />
            <YAxis
              domain={domain ?? ['auto', 'auto']}
              stroke={AXIS_COLOR}
              tick={{ fontSize: 11, fill: AXIS_COLOR }}
              width={46}
            />
            <Tooltip
              contentStyle={{
                background: '#0d1424',
                border: '1px solid #1e2b45',
                borderRadius: 10,
                fontSize: 12,
              }}
              labelFormatter={(value: string) => formatAxisTime(value, rangeHours)}
              formatter={(value: unknown, name: unknown) => {
                const numeric = Array.isArray(value) ? value[0] : value
                const label =
                  numeric === null || numeric === undefined || Number.isNaN(Number(numeric))
                    ? 'sensor unavailable'
                    : `${numeric}${unit ?? ''}`
                return [label, String(name)]
              }}
            />
            <Legend
              wrapperStyle={{ fontSize: 12, color: AXIS_COLOR }}
              iconType="plainline"
            />
            {series.map((item) => (
              <Line
                key={String(item.key)}
                type="monotone"
                dataKey={String(item.key)}
                name={item.name}
                stroke={item.color}
                strokeWidth={2}
                dot={false}
                connectNulls
                isAnimationActive={false}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      )}
    </section>
  )
}

export default ChartPanel