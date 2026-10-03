'use client'

/**
 * `usePolling` runs an async loader on an interval and pauses while the tab is
 * hidden, so a dashboard left open overnight does not hammer the API.
 */

import { useCallback, useEffect, useRef, useState } from 'react'

export interface PollingState<T> {
  data: T | null
  error: Error | null
  loading: boolean
  refreshing: boolean
  lastUpdated: Date | null
  refresh: () => Promise<void>
}

export function usePolling<T>(
  loader: () => Promise<T>,
  intervalSeconds: number,
  options: { enabled?: boolean; deps?: unknown[] } = {},
): PollingState<T> {
  const enabled = options.enabled ?? true
  const deps = options.deps ?? []

  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<Error | null>(null)
  const [loading, setLoading] = useState(enabled)
  const [refreshing, setRefreshing] = useState(false)
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null)

  const loaderRef = useRef(loader)
  loaderRef.current = loader
  const mountedRef = useRef(true)

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
    }
  }, [])

  const refresh = useCallback(async () => {
    setRefreshing(true)
    try {
      const result = await loaderRef.current()
      if (!mountedRef.current) return
      setData(result)
      setError(null)
      setLastUpdated(new Date())
    } catch (caught) {
      if (!mountedRef.current) return
      setError(caught instanceof Error ? caught : new Error(String(caught)))
    } finally {
      if (mountedRef.current) {
        setLoading(false)
        setRefreshing(false)
      }
    }
  }, [])

  useEffect(() => {
    if (!enabled) {
      setLoading(false)
      return
    }
    void refresh()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, refresh, ...deps])

  useEffect(() => {
    if (!enabled || intervalSeconds <= 0) return
    const intervalMs = Math.max(5, intervalSeconds) * 1000
    const timer = setInterval(() => {
      if (typeof document !== 'undefined' && document.hidden) return
      void refresh()
    }, intervalMs)
    return () => clearInterval(timer)
  }, [enabled, intervalSeconds, refresh])

  return { data, error, loading, refreshing, lastUpdated, refresh }
}