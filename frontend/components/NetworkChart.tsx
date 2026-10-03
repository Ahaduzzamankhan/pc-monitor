'use client'

import { ChartPanel } from './charts/ChartPanel'
import type { TelemetryPoint } from '@/lib/types'

export interface NetworkChartProps {
  points: TelemetryPoint[]
  rangeHours: number
}

/** Aggregate download/upload throughput (loopback traffic is excluded). */
export function NetworkChart({ points, rangeHours }: NetworkChartProps) {
  return (
    <ChartPanel
      testId="network-chart"
      title="Network throughput"
      description="Download and upload speed"
      points={points}
      rangeHours={rangeHours}
      unit=" Mbps"
      series={[
        { key: 'downloadMbps', name: 'Download', color: '#38bdf8' },
        { key: 'uploadMbps', name: 'Upload', color: '#34d399' },
      ]}
    />
  )
}

export default NetworkChart