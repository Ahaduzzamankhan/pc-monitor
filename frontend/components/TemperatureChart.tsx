'use client'

import { ChartPanel } from './charts/ChartPanel'
import type { TelemetryPoint } from '@/lib/types'

export interface TemperatureChartProps {
  points: TelemetryPoint[]
  rangeHours: number
}

/** CPU and GPU temperatures (both null on machines without thermal sensors). */
export function TemperatureChart({ points, rangeHours }: TemperatureChartProps) {
  return (
    <ChartPanel
      testId="temperature-chart"
      title="Temperatures"
      description="Sensors report null where the hardware exposes no thermal data"
      points={points}
      rangeHours={rangeHours}
      unit=" °C"
      emptyTitle="No temperature sensors"
      emptyDescription="Windows does not expose CPU/GPU temperatures to user-mode apps by default."
      series={[
        { key: 'cpuTemperature', name: 'CPU', color: '#fbbf24' },
        { key: 'gpuTemperature', name: 'GPU', color: '#f472b6' },
      ]}
    />
  )
}

export default TemperatureChart