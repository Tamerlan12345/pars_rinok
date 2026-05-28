import { useState, useCallback } from 'react'
import { analysisApi } from '../api/client.js'

/**
 * useAnalysis — manages AI analysis requests and history.
 *
 * runAnalysis(ticker, period, interval):
 *   Posts to /api/analysis/run and stores the result.
 *
 * fetchHistory(ticker, limit):
 *   Retrieves the analysis history list for a given ticker.
 *
 * fetchById(id):
 *   Fetches a single analysis record by ID and makes it current.
 */
export function useAnalysis() {
  const [analysis, setAnalysis]     = useState(null)
  const [history, setHistory]       = useState([])
  const [loading, setLoading]       = useState(false)
  const [historyLoading, setHistoryLoading] = useState(false)
  const [error, setError]           = useState('')

  const runAnalysis = useCallback(async (ticker, period, interval) => {
    if (!ticker?.trim()) return
    setLoading(true)
    setError('')
    try {
      const r = await analysisApi.runAnalysis(ticker.trim().toUpperCase(), period, interval)
      setAnalysis(r.data)
      return r.data
    } catch (err) {
      const msg = err.response?.data?.detail || err.message || 'Analysis request failed'
      setError(msg)
      return null
    } finally {
      setLoading(false)
    }
  }, [])

  const fetchHistory = useCallback(async (ticker, limit = 10) => {
    setHistoryLoading(true)
    try {
      const r = await analysisApi.getHistory(ticker || '', limit)
      const items = r.data || []
      setHistory(items)
      // If no current analysis and history exists, seed from most recent
      if (!analysis && items.length > 0) {
        setAnalysis(items[0])
      }
      return items
    } catch {
      // History is informational; do not surface to user as blocking error
      return []
    } finally {
      setHistoryLoading(false)
    }
  }, [analysis])

  const fetchById = useCallback(async (id) => {
    if (!id) return null
    setLoading(true)
    setError('')
    try {
      const r = await analysisApi.getById(id)
      setAnalysis(r.data)
      return r.data
    } catch (err) {
      const msg = err.response?.data?.detail || err.message || 'Failed to load analysis'
      setError(msg)
      return null
    } finally {
      setLoading(false)
    }
  }, [])

  const clearError = useCallback(() => setError(''), [])

  return {
    analysis,
    history,
    loading,
    historyLoading,
    error,
    runAnalysis,
    fetchHistory,
    fetchById,
    clearError
  }
}
