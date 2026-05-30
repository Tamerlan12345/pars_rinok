import { useEffect, useRef, useCallback } from 'react'
import { createChart, CrosshairMode, LineStyle } from 'lightweight-charts'

function ChartSkeleton() {
  return (
    <div style={{ height: '400px', display: 'flex', flexDirection: 'column', gap: '8px', padding: '8px' }}>
      <div className="skeleton" style={{ height: '100%', borderRadius: '8px' }} />
    </div>
  )
}

function EmptyState({ ticker }) {
  return (
    <div className="empty-state" style={{ height: '400px' }}>
      <div className="empty-state-icon">◈</div>
      <div className="empty-state-title">No chart data</div>
      <div className="empty-state-sub">
        {ticker
          ? `Fetch data for ${ticker.toUpperCase()} then click "↺ Chart" to load`
          : 'Enter a ticker symbol and fetch data'}
      </div>
    </div>
  )
}

export default function CandleChart({ candles = [], loading = false, ticker = '' }) {
  const containerRef = useRef(null)
  const chartRef = useRef(null)
  const candleSeriesRef = useRef(null)
  const volumeSeriesRef = useRef(null)
  const resizeObserverRef = useRef(null)

  const destroyChart = useCallback(() => {
    if (resizeObserverRef.current) {
      resizeObserverRef.current.disconnect()
      resizeObserverRef.current = null
    }
    if (chartRef.current) {
      chartRef.current.remove()
      chartRef.current = null
      candleSeriesRef.current = null
      volumeSeriesRef.current = null
    }
  }, [])

  const initChart = useCallback(() => {
    if (!containerRef.current) return
    destroyChart()

    const container = containerRef.current
    const width = container.clientWidth
    const height = 400

    const chart = createChart(container, {
      width,
      height,
      layout: {
        background: { color: 'var(--bg-primary)' || '#0a0e1a' },
        textColor: '#9ca3af',
        fontSize: 12,
        fontFamily: "'Inter', system-ui, sans-serif"
      },
      grid: {
        vertLines: { color: '#1f2937', style: LineStyle.Dotted },
        horzLines: { color: '#1f2937', style: LineStyle.Dotted }
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: {
          color: 'rgba(99,102,241,0.5)',
          labelBackgroundColor: '#6366f1'
        },
        horzLine: {
          color: 'rgba(99,102,241,0.5)',
          labelBackgroundColor: '#6366f1'
        }
      },
      rightPriceScale: {
        borderColor: '#1f2937',
        scaleMargins: { top: 0.1, bottom: 0.25 }
      },
      timeScale: {
        borderColor: '#1f2937',
        timeVisible: true,
        secondsVisible: false,
        fixLeftEdge: true,
        fixRightEdge: false
      },
      handleScroll: true,
      handleScale: true
    })

    chartRef.current = chart

    // Candlestick series
    const candleSeries = chart.addCandlestickSeries({
      upColor:          '#10b981',
      downColor:        '#ef4444',
      borderUpColor:    '#10b981',
      borderDownColor:  '#ef4444',
      wickUpColor:      '#10b981',
      wickDownColor:    '#ef4444'
    })
    candleSeriesRef.current = candleSeries

    // Volume histogram series
    const volumeSeries = chart.addHistogramSeries({
      color: '#6366f1',
      priceFormat: { type: 'volume' },
      priceScaleId: 'volume',
      scaleMargins: { top: 0.8, bottom: 0 }
    })
    chart.priceScale('volume').applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } })
    volumeSeriesRef.current = volumeSeries

    // Resize observer
    const observer = new ResizeObserver(entries => {
      const entry = entries[0]
      if (entry && chartRef.current) {
        chartRef.current.applyOptions({ width: entry.contentRect.width })
      }
    })
    observer.observe(container)
    resizeObserverRef.current = observer

    return chart
  }, [destroyChart])

  // Init chart once on mount
  useEffect(() => {
    initChart()
    return destroyChart
  }, [initChart, destroyChart])

  // Feed data to chart when candles change
  useEffect(() => {
    if (!candleSeriesRef.current || !volumeSeriesRef.current) return
    if (candles.length === 0) {
      candleSeriesRef.current.setData([])
      volumeSeriesRef.current.setData([])
      return
    }

    // Normalize, sort numerically, and deduplicate by time
    const sorted = [...candles].sort((a, b) => {
      const ta = Number(a.time)
      const tb = Number(b.time)
      return ta - tb
    })

    const uniqueSorted = []
    let lastTime = null
    for (const c of sorted) {
      if (c.time !== lastTime) {
        uniqueSorted.push(c)
        lastTime = c.time
      }
    }

    const ohlcv = uniqueSorted.map(c => ({
      time: c.time,
      open:  Number(c.open),
      high:  Number(c.high),
      low:   Number(c.low),
      close: Number(c.close)
    }))

    const volumes = uniqueSorted.map(c => ({
      time:  c.time,
      value: Number(c.volume) || 0,
      color: Number(c.close) >= Number(c.open)
        ? 'rgba(16,185,129,0.4)'
        : 'rgba(239,68,68,0.4)'
    }))

    try {
      candleSeriesRef.current.setData(ohlcv)
      volumeSeriesRef.current.setData(volumes)
      chartRef.current?.timeScale().fitContent()
    } catch (err) {
      // Lightweight-charts throws if data is not monotonically increasing —
      // this is a data quality issue from upstream, not a render bug.
      console.warn('[CandleChart] setData error:', err.message)
    }
  }, [candles])

  if (loading) return <ChartSkeleton />
  if (!loading && candles.length === 0) {
    return (
      <>
        <EmptyState ticker={ticker} />
        {/* Keep the container in DOM so the chart stays initialized */}
        <div ref={containerRef} style={{ display: 'none' }} />
      </>
    )
  }

  return (
    <div
      className="chart-container"
      style={{ animation: 'fadeIn 0.3s ease' }}
    >
      <div ref={containerRef} className="chart-inner" style={{ height: '400px' }} />
    </div>
  )
}
