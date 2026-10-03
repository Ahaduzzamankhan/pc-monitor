'use client'

import { ChartPanel } from './charts/ChartPanel'
import type { TelemetryPoint } from '@/lib/types'

export interface CpuChartProps {
  points: TelemetryPoint[]
  rangeHours: number
}

/** Overall CPU utilisation over the selected window. */
export function CpuChart({ points, rangeHours }: CpuChartProps) {
  return (
    <ChartPanel
      testId="cpu-chart"
      title="CPU usage"
      description="Total processor utilisation"
      points={points}
      rangeHours={rangeHours}
      unit="%"
      domain={[0, 100]}
      series={[{ key: 'cpuUsage', name: 'CPU', color: '#38bdf8' }]}
    />
  )
}

export default CpuChart