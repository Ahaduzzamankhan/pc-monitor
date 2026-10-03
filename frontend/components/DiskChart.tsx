'use client'

import { ChartPanel } from './charts/ChartPanel'
import type { TelemetryPoint } from '@/lib/types'

export interface DiskChartProps {
  points: TelemetryPoint[]
  rangeHours: number
}

/** System volume utilisation over the selected window. */
export function DiskChart({ points, rangeHours }: DiskChartProps) {
  return (
    <ChartPanel
      testId="disk-chart"
      title="Disk usage"
      description="Capacity used on the system volume"
      points={points}
      rangeHours={rangeHours}
      unit="%"
      domain={[0, 100]}
      series={[{ key: 'diskUsage', name: 'Disk', color: '#60a5fa' }]}
    />
  )
}

export default DiskChart