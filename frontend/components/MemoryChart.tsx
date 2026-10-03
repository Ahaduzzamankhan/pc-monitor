'use client'

import { ChartPanel } from './charts/ChartPanel'
import type { TelemetryPoint } from '@/lib/types'

export interface MemoryChartProps {
  points: TelemetryPoint[]
  rangeHours: number
}

/** Physical memory utilisation over the selected window. */
export function MemoryChart({ points, rangeHours }: MemoryChartProps) {
  return (
    <ChartPanel
      testId="memory-chart"
      title="Memory (RAM)"
      description="Physical memory in use"
      points={points}
      rangeHours={rangeHours}
      unit="%"
      domain={[0, 100]}
      series={[{ key: 'ramUsage', name: 'RAM', color: '#34d399' }]}
    />
  )
}

export default MemoryChart