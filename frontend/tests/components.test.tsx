import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { CpuChart } from '@/components/CpuChart'
import { DeviceCard } from '@/components/DeviceCard'
import { DeviceGrid } from '@/components/DeviceGrid'
import { NetworkChart } from '@/components/NetworkChart'
import { RangeSelector } from '@/components/RangeSelector'
import { StatusBadge } from '@/components/StatusBadge'
import { TemperatureChart } from '@/components/TemperatureChart'
import type { Device, TelemetryPoint } from '@/lib/types'

const onlineDevice: Device = {
  deviceId: 'PC-00000001',
  name: 'Home PC',
  online: true,
  status: 'online',
  lastSeen: new Date().toISOString(),
  secondsSinceLastSeen: 4,
  createdAt: new Date().toISOString(),
  agentVersion: '1.0.0',
  os: 'Windows 11 Pro',
  architecture: 'AMD64',
  hostname: 'DESKTOP-ABC',
  cpuModel: 'AMD Ryzen 7 5800X',
  gpuModel: 'NVIDIA GeForce RTX 3070',
  ramTotalMB: 32768,
  diskTotalGB: 931,
  telemetryIntervalSeconds: 30,
  startupEnabled: true,
  metrics: {
    timestamp: new Date().toISOString(),
    cpuUsage: 42.5,
    gpuUsage: 61,
    ramUsage: 62.5,
    cpuTemperature: 55,
    gpuTemperature: 58,
    diskUsage: 71,
    downloadMbps: 8.4,
    uploadMbps: 1.2,
    batteryPercent: null,
  },
}

const offlineDevice: Device = {
  ...onlineDevice,
  deviceId: 'PC-00000003',
  name: 'Laptop',
  online: false,
  status: 'offline',
  secondsSinceLastSeen: 14 * 60,
  lastSeen: new Date(Date.now() - 14 * 60 * 1000).toISOString(),
  metrics: null,
}

function point(overrides: Partial<TelemetryPoint> = {}): TelemetryPoint {
  return {
    timestamp: new Date().toISOString(),
    cpuUsage: 40,
    gpuUsage: 55,
    ramUsage: 61,
    cpuTemperature: 52,
    gpuTemperature: 57,
    diskUsage: 70,
    downloadMbps: 8.4,
    uploadMbps: 1.2,
    diskReadMbps: 0.4,
    diskWriteMbps: 0.1,
    ...overrides,
  }
}

describe('StatusBadge', () => {
  it('renders ONLINE for a reporting device', () => {
    render(<StatusBadge online status="online" />)
    expect(screen.getByTestId('status-badge')).toHaveTextContent('online')
    expect(screen.getByTestId('status-badge')).toHaveAttribute('data-status', 'online')
  })

  it('renders OFFLINE and never pulses', () => {
    render(<StatusBadge online={false} />)
    const badge = screen.getByTestId('status-badge')
    expect(badge).toHaveTextContent('offline')
    expect(badge.className).not.toContain('badge--pulse')
  })
})

describe('DeviceCard', () => {
  it('shows the headline metrics for an online PC', () => {
    render(<DeviceCard device={onlineDevice} />)
    const card = screen.getByTestId('device-card')
    expect(card).toHaveTextContent('Home PC')
    expect(card).toHaveTextContent('PC-00000001')
    expect(card).toHaveTextContent('43%') // CPU 42.5 rounds to 43
    expect(card).toHaveTextContent('61%') // GPU
    expect(card).toHaveTextContent('63%') // RAM 62.5 rounds to 63
    expect(card).toHaveTextContent('55°C')
  })

  it('shows "last seen" for an offline PC and hides unavailable sensors', () => {
    render(<DeviceCard device={offlineDevice} />)
    const card = screen.getByTestId('device-card')
    expect(card).toHaveTextContent('offline')
    expect(card).toHaveTextContent('Last seen')
    expect(card).toHaveTextContent('14 minutes ago')
    expect(card).toHaveTextContent('—') // no temperature available
  })

  it('links to the dynamic device route', () => {
    render(<DeviceCard device={onlineDevice} />)
    expect(screen.getByTestId('device-card')).toHaveAttribute(
      'href',
      '/dashboard/devices/PC-00000001',
    )
  })
})

describe('DeviceGrid', () => {
  it('renders one card per device', () => {
    render(<DeviceGrid devices={[onlineDevice, offlineDevice]} />)
    expect(screen.getAllByTestId('device-card')).toHaveLength(2)
  })

  it('explains how to add a PC when nothing is registered', () => {
    render(<DeviceGrid devices={[]} />)
    expect(screen.getByTestId('empty-state')).toHaveTextContent('No PCs registered yet')
  })

  it('surfaces API errors with a retry action', async () => {
    const onRetry = vi.fn()
    render(
      <DeviceGrid devices={null} error={new Error('Cannot reach the PC Monitor API.')} onRetry={onRetry} />,
    )
    expect(screen.getByTestId('error-state')).toHaveTextContent('Cannot reach the PC Monitor API.')
    await userEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(onRetry).toHaveBeenCalledOnce()
  })
})

describe('charts with empty history', () => {
  it('renders a friendly empty state instead of a broken canvas', () => {
    render(<CpuChart points={[]} rangeHours={6} />)
    expect(screen.getByTestId('cpu-chart')).toHaveTextContent('No data in this range')
  })

  it('explains when temperatures are unavailable', () => {
    render(<TemperatureChart points={[]} rangeHours={6} />)
    expect(screen.getByTestId('temperature-chart')).toHaveTextContent('No temperature sensors')
  })

  it('explains when the GPU exposes no metrics', () => {
    render(<NetworkChart points={[]} rangeHours={1} />)
    expect(screen.getByTestId('network-chart')).toHaveTextContent('No data in this range')
  })
})

describe('charts with data', () => {
  it('renders chart content for CPU instead of the empty state', () => {
    const { container } = render(
      <CpuChart points={[point(), point({ cpuUsage: 80 })]} rangeHours={6} />,
    )
    const card = screen.getByTestId('cpu-chart')
    expect(card).toHaveTextContent('CPU usage')
    expect(screen.queryByTestId('empty-state')).toBeNull()
    // ResponsiveContainer renders its wrapper even when jsdom reports 0 width.
    expect(
      container.querySelector('.recharts-responsive-container, .recharts-wrapper, svg'),
    ).toBeTruthy()
  })
})

describe('RangeSelector', () => {
  it('offers 1h, 6h, 24h and 7d and reports selection', async () => {
    const onChange = vi.fn()
    render(<RangeSelector value="6h" onChange={onChange} />)
    for (const range of ['1h', '6h', '24h', '7d']) {
      expect(screen.getByTestId(`range-${range}`)).toBeInTheDocument()
    }
    await userEvent.click(screen.getByTestId('range-24h'))
    expect(onChange).toHaveBeenCalledWith('24h')
  })

  it('disables ranges the backend cannot serve', () => {
    render(<RangeSelector value="1h" onChange={vi.fn()} available={['1h', '6h']} />)
    expect(screen.getByTestId('range-7d')).toBeDisabled()
  })
})