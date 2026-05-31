import axios from 'axios'

const BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

const client = axios.create({
  baseURL: BASE_URL,
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json'
  }
})

function toChartTime(value) {
  if (typeof value === 'number') return value
  if (!value) return value
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? value : Math.floor(parsed.getTime() / 1000)
}

function normalizeCandle(candle) {
  if (!candle || typeof candle !== 'object') return candle
  return {
    ...candle,
    time: candle.time ?? toChartTime(candle.timestamp)
  }
}

function normalizeAnalysis(item) {
  if (!item || typeof item !== 'object') return item
  return {
    ...item,
    ticker: item.ticker ?? item.ticker_symbol,
    coarse_tokens: item.coarse_tokens ?? item.tokens_coarse ?? [],
    fine_tokens: item.fine_tokens ?? item.tokens_fine ?? [],
    summary: item.summary ?? item.gemini_summary,
    signals: item.signals ?? item.gemini_signals ?? [],
    sentiment: item.sentiment ?? item.gemini_sentiment,
    confidence: item.confidence ?? item.gemini_confidence,
    key_levels: item.key_levels ?? item.gemini_key_levels ?? [],
    risk_factors: item.risk_factors ?? item.gemini_risk_factors ?? [],
    forecast_direction: item.forecast_direction ?? null,
    forecast_price_target: item.forecast_price_target ?? null,
    forecast_period: item.forecast_period ?? null,
    forecast_rationale: item.forecast_rationale ?? null,
  }
}

function normalizeNews(item) {
  if (!item || typeof item !== 'object') return item
  return {
    ...item,
    ticker: item.ticker ?? item.ticker_symbol
  }
}

function withData(response, data) {
  return { ...response, data }
}

function formatDetail(detail) {
  if (Array.isArray(detail)) {
    return detail
      .map(item => item?.msg || item?.message || String(item))
      .join('; ')
  }
  return detail
}

client.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('auth_token')
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => Promise.reject(error)
)

client.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.data?.detail) {
      error.response.data.detail = formatDetail(error.response.data.detail)
    }
    if (error.response?.status === 401) {
      localStorage.removeItem('auth_token')
      if (typeof window !== 'undefined' && !window.location.pathname.includes('/login')) {
        window.dispatchEvent(new CustomEvent('auth:expired'))
      }
    }
    return Promise.reject(error)
  }
)

export const authApi = {
  login(username, password) {
    return client.post('/api/auth/login', { username, password })
  }
}

export const marketApi = {
  fetchData(ticker, period, interval) {
    return client.get('/api/market/fetch', {
      params: { ticker, period, interval }
    }).then(r => withData(r, {
      ...r.data,
      candles: Array.isArray(r.data?.candles) ? r.data.candles.map(normalizeCandle) : []
    }))
  },

  getTickers() {
    return client.get('/api/market/tickers')
  },

  addTicker(symbol, name) {
    return client.post('/api/market/tickers', { symbol, name })
  },

  getCandles(ticker, interval, limit = 300) {
    return client.get('/api/market/candles', {
      params: { ticker, interval, limit }
    }).then(r => withData(r, Array.isArray(r.data) ? r.data.map(normalizeCandle) : []))
  }
}

export const analysisApi = {
  runAnalysis(ticker, period, interval, forecast_horizon = '3 месяца') {
    return client.post('/api/analysis/run', { ticker, period, interval, forecast_horizon })
      .then(r => withData(r, normalizeAnalysis(r.data)))
  },

  getHistory(ticker, limit = 10) {
    return client.get('/api/analysis/history', {
      params: { ticker, limit }
    }).then(r => withData(r, Array.isArray(r.data) ? r.data.map(normalizeAnalysis) : []))
  },

  getById(id) {
    return client.get(`/api/analysis/${id}`)
      .then(r => withData(r, normalizeAnalysis(r.data)))
  }
}

export const newsApi = {
  fetchNews(ticker) {
    return client.get('/api/news/fetch', { params: { ticker } })
      .then(r => withData(r, Array.isArray(r.data) ? r.data.map(normalizeNews) : []))
  },

  fetchGeneralNews() {
    return client.get('/api/news/general')
      .then(r => withData(r, Array.isArray(r.data) ? r.data.map(normalizeNews) : []))
  },

  getLatest(limit = 20) {
    return client.get('/api/news/latest', { params: { limit } })
      .then(r => withData(r, Array.isArray(r.data) ? r.data.map(normalizeNews) : []))
  },

  getByTicker(symbol, limit = 20) {
    return client.get(`/api/news/ticker/${symbol}`, { params: { limit } })
      .then(r => withData(r, Array.isArray(r.data) ? r.data.map(normalizeNews) : []))
  }
}

export const logsApi = {
  getRecent(limit = 100) {
    return client.get('/api/logs/recent', { params: { limit } })
  }
}

export const healthApi = {
  check() {
    return client.get('/health')
  }
}

export default client
