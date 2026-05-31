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

export default function CandleChart({ candles = [], loading = false, ticker = '', analysis = null }) {
  const containerRef = useRef(null)
  const chartRef = useRef(null)
  const candleSeriesRef = useRef(null)
  const volumeSeriesRef = useRef(null)
  const resizeObserverRef = useRef(null)
  const priceLinesRef = useRef([])

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
      priceLinesRef.current = []
    }
  }, [])

  const initChart = useCallback(() => {
    if (!containerRef.current) return
    destroyChart()

    const container = containerRef.current
    const width = container.clientWidth || container.offsetWidth || 600
    const height = 400

    const chart = createChart(container, {
      width,
      height,
      layout: {
        background: { color: '#0a0e1a' },
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

    // Volume histogram series (overlaid on the same pane, pinned to the bottom)
    const volumeSeries = chart.addHistogramSeries({
      color: '#6366f1',
      priceFormat: { type: 'volume' },
      priceScaleId: 'volume',
      scaleMargins: { top: 0.8, bottom: 0 }
    })
    chart.priceScale('volume').applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } })
    volumeSeriesRef.current = volumeSeries

    // Keep chart width in sync with container
    const observer = new ResizeObserver(entries => {
      const entry = entries[0]
      if (entry && chartRef.current) {
        chartRef.current.applyOptions({ width: entry.contentRect.width })
      }
    })
    observer.observe(container)
    resizeObserverRef.current = observer
  }, [destroyChart])

  // Destroy chart on unmount
  useEffect(() => {
    return destroyChart
  }, [destroyChart])

  // (Re-)initialize the chart whenever loading transitions to false.
  // The chart container is ALWAYS in the DOM so containerRef is always valid here.
  // We destroy any stale chart first (handles ticker/interval changes).
  useEffect(() => {
    if (loading) return
    // Always (re)create the chart when loading finishes so we are on the
    // currently rendered, visible container — never on a stale/hidden div.
    initChart()
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loading]) // intentionally omit initChart — it is stable but we only want this on loading flip

  // Feed data to chart whenever candles array changes
  useEffect(() => {
    if (!candleSeriesRef.current || !volumeSeriesRef.current) return
    if (candles.length === 0) {
      candleSeriesRef.current.setData([])
      volumeSeriesRef.current.setData([])
      return
    }

    // Sort by unix timestamp ascending, then deduplicate by calendar day
    const sorted = [...candles].sort((a, b) => Number(a.time) - Number(b.time))

    const uniqueSorted = []
    const seenTimes = new Set()

    for (const c of sorted) {
      const d = new Date(Number(c.time) * 1000)
      if (Number.isNaN(d.getTime())) continue

      // lightweight-charts requires YYYY-MM-DD strings for daily data
      const timeStr = `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, '0')}-${String(d.getUTCDate()).padStart(2, '0')}`

      if (seenTimes.has(timeStr)) continue
      seenTimes.add(timeStr)

      const o = Number(c.open)
      let h = Number(c.high)
      let l = Number(c.low)
      const cl = Number(c.close)
      const v = Number(c.volume) || 0

      // Clamp wicks to valid OHLC range — lightweight-charts rejects impossible values
      if (h < o) h = o
      if (h < cl) h = cl
      if (l > o) l = o
      if (l > cl) l = cl

      if (Number.isNaN(o) || Number.isNaN(h) || Number.isNaN(l) || Number.isNaN(cl)) continue

      uniqueSorted.push({
        time: timeStr,
        open: o, high: h, low: l, close: cl,
        value: v,
        color: cl >= o ? 'rgba(16,185,129,0.4)' : 'rgba(239,68,68,0.4)'
      })
    }

    const ohlcv   = uniqueSorted.map(({ time, open, high, low, close }) => ({ time, open, high, low, close }))
    const volumes = uniqueSorted.map(({ time, value, color }) => ({ time, value, color }))

    try {
      candleSeriesRef.current.setData(ohlcv)
      volumeSeriesRef.current.setData(volumes)
      chartRef.current?.timeScale().fitContent()
    } catch (err) {
      // Data quality issue from upstream (non-monotonic timestamps), not a render bug
      console.warn('[CandleChart] setData error:', err.message)
    }
  }, [candles])

  // Draw price lines for AI forecast and key levels
  useEffect(() => {
    if (!candleSeriesRef.current) return
    
    // Clear old lines
    priceLinesRef.current.forEach(line => {
      try {
        candleSeriesRef.current.removePriceLine(line)
      } catch (e) {}
    })
    priceLinesRef.current = []

    if (!analysis) return

    const keyLevels = analysis.key_levels || analysis.gemini_key_levels || []
    const target = analysis.forecast_price_target
    const dir = analysis.forecast_direction

    if (Array.isArray(keyLevels)) {
      keyLevels.forEach(lvl => {
        const line = candleSeriesRef.current.createPriceLine({
          price: Number(lvl),
          color: 'rgba(0, 180, 216, 0.9)', // Cyan/Blue factor
          lineWidth: 2,
          lineStyle: LineStyle.Dashed,
          axisLabelVisible: true,
          title: 'Уровень',
        })
        priceLinesRef.current.push(line)
      })
    }

    if (target != null) {
      // Highlight forecast target with thick bright cyan
      const line = candleSeriesRef.current.createPriceLine({
        price: Number(target),
        color: '#00e5ff',
        lineWidth: 3,
        lineStyle: LineStyle.Solid,
        axisLabelVisible: true,
        title: 'Цель (ИИ)',
      })
      priceLinesRef.current.push(line)
    }
  }, [analysis, candles])

  // The container div is ALWAYS rendered so that:
  //   a) containerRef is always a real, visible DOM node
  //   b) initChart never runs against a zero-width hidden div
  // Skeleton and EmptyState are rendered as absolute overlays on top.
  return (
    <div
      className="chart-container"
      style={{ position: 'relative', animation: 'fadeIn 0.3s ease', minHeight: '400px' }}
    >
      {loading && (
        <div style={{ position: 'absolute', inset: 0, zIndex: 10 }}>
          <ChartSkeleton />
        </div>
      )}
      {!loading && candles.length === 0 && (
        <div style={{ position: 'absolute', inset: 0, zIndex: 10 }}>
          <EmptyState ticker={ticker} />
        </div>
      )}
      <div ref={containerRef} className="chart-inner" style={{ height: '400px' }} />
    </div>
  )
}
