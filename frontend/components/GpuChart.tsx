'use client'

import { ChartPanel } from './charts/ChartPanel'
import type { TelemetryPoint } from '@/lib/types'

export interface GpuChartProps {
  points: TelemetryPoint[]
  rangeHours: number
  /** Shown when the machine has no supported GPU telemetry. */
  gpuName?: string | null
}

/** GPU utilisation over the selected window (null on machines without a GPU). */
export function GpuChart({ points, rangeHours, gpuName }: GpuChartProps) {
  return (
    <ChartPanel
      testId="gpu-chart"
      title="GPU usage"
      description={gpuName ? `${gpuName}` : 'Graphics adapter utilisation'}
      points={points}
      rangeHours={rangeHours}
      unit="%"
      domain={[0, 100]}
      emptyTitle="GPU telemetry unavailable"
      emptyDescription="This machine does not expose GPU metrics (common for integrated GPUs)."
      series={[{ key: 'gpuUsage', name: 'GPU', color: '#a78bfa' }]}
    />
  )
}

export default GpuChart