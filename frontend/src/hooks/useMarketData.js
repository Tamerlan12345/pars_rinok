import { useState, useCallback } from 'react'
import { marketApi } from '../api/client.js'

/**
 * useMarketData — fetches OHLCV candles for a given ticker.
 *
 * fetchData(ticker, period, interval):
 *   1. Calls marketApi.fetchData to pull data from the upstream source.
 *   2. Then calls marketApi.getCandles to retrieve the stored candles.
 *
 * loadCandles(ticker, interval, limit):
 *   Loads candles directly from cache without triggering an upstream fetch.
 */
export function useMarketData() {
  const [candles, setCandles]       = useState([])
  const [loading, setLoading]       = useState(false)
  const [error, setError]           = useState('')
  const [fromCache, setFromCache]   = useState(false)

  const fetchData = useCallback(async (ticker, period, interval) => {
    if (!ticker?.trim()) return
    setLoading(true)
    setError('')
    setFromCache(false)
    try {
      await marketApi.fetchData(ticker.trim().toUpperCase(), period, interval)
      const r = await marketApi.getCandles(ticker.trim().toUpperCase(), interval, 300)
      setCandles(r.data || [])
      setFromCache(false)
    } catch (err) {
      const msg = err.response?.data?.detail || err.message || 'Failed to fetch market data'
      setError(msg)
      setCandles([])
    } finally {
      setLoading(false)
    }
  }, [])

  const loadCandles = useCallback(async (ticker, interval, limit = 300) => {
    if (!ticker?.trim()) return
    setLoading(true)
    setError('')
    try {
      const r = await marketApi.getCandles(ticker.trim().toUpperCase(), interval, limit)
      setCandles(r.data || [])
      setFromCache(true)
    } catch (err) {
      const msg = err.response?.data?.detail || err.message || 'Failed to load candles'
      setError(msg)
    } finally {
      setLoading(false)
    }
  }, [])

  const clearError = useCallback(() => setError(''), [])

  return { candles, loading, error, fromCache, fetchData, loadCandles, clearError }
}
