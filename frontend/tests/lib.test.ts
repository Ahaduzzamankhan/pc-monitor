import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  cn,
  formatPercent,
  formatRelativeTime,
  formatSpeed,
  formatTemperature,
  temperatureLevel,
  usageLevel,
} from '@/lib/utils'
import { ApiError, getDevices, getTelemetry, deleteDevice } from '@/lib/api'

afterEach(() => {
  vi.restoreAllMocks()
})

describe('formatting helpers', () => {
  it('formats percentages and temperatures, and reports missing sensors', () => {
    expect(formatPercent(42.5)).toBe('43%')
    expect(formatPercent(null)).toBe('—')
    expect(formatTemperature(55.4)).toBe('55°C')
    expect(formatTemperature(undefined)).toBe('—')
  })

  it('formats speeds', () => {
    expect(formatSpeed(8.4)).toBe('8.40 Mbps')
    expect(formatSpeed(null)).toBe('—')
    expect(formatSpeed(0)).toBe('0 Mbps')
  })

  it('formats relative times in local time', () => {
    const minutesAgo = new Date(Date.now() - 14 * 60 * 1000).toISOString()
    expect(formatRelativeTime(minutesAgo)).toMatch(/14 minutes ago|14 mins? ago/)
    expect(formatRelativeTime(new Date().toISOString())).toBe('just now')
    expect(formatRelativeTime(null)).toBe('unknown')
  })

  it('classifies usage and temperature severity', () => {
    expect(usageLevel(42)).toBe('ok')
    expect(usageLevel(80)).toBe('warn')
    expect(usageLevel(97)).toBe('critical')
    expect(usageLevel(null)).toBe('unknown')
    expect(temperatureLevel(55)).toBe('ok')
    expect(temperatureLevel(72)).toBe('warn')
    expect(temperatureLevel(90)).toBe('critical')
  })

  it('joins class names', () => {
    expect(cn('a', false, undefined, 'b')).toBe('a b')
  })
})

describe('api client', () => {
  const payload = {
    devices: [],
    count: 0,
    onlineCount: 0,
    generatedAt: new Date().toISOString(),
    refreshAfterSeconds: 15,
  }

  it('requests the device list from the backend', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      text: async () => JSON.stringify(payload),
    })
    vi.stubGlobal('fetch', fetchMock)

    await expect(getDevices()).resolves.toEqual(payload)
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/api/devices'),
      expect.objectContaining({ cache: 'no-store' }),
    )
  })

  it('requests only the selected range', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      text: async () => JSON.stringify({ points: [] }),
    })
    vi.stubGlobal('fetch', fetchMock)

    await getTelemetry('PC-1', '24h')
    expect(fetchMock.mock.calls[0][0]).toContain('/api/devices/PC-1/telemetry?range=24h')
  })

  it('wraps API errors in ApiError', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: false,
        status: 404,
        text: async () =>
          JSON.stringify({ error: { code: 'device_not_found', message: 'unknown device' } }),
      }),
    )
    await expect(getDevices()).rejects.toBeInstanceOf(ApiError)
  })

  it('reports network failures as ApiError with status 0', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockRejectedValue(new TypeError('Failed to fetch')),
    )
    try {
      await getDevices()
      throw new Error('expected rejection')
    } catch (error) {
      expect(error).toBeInstanceOf(ApiError)
      expect((error as ApiError).status).toBe(0)
      expect((error as ApiError).friendlyMessage).toContain('Cannot reach')
    }
  })

  it('sends DELETE for device removal', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      text: async () => JSON.stringify({ deleted: true, tokenRevoked: true }),
    })
    vi.stubGlobal('fetch', fetchMock)

    await deleteDevice('PC-1')
    expect(fetchMock.mock.calls[0][1]).toMatchObject({ method: 'DELETE' })
  })
})