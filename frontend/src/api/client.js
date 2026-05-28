import axios from 'axios'

const BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

const client = axios.create({
  baseURL: BASE_URL,
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json'
  }
})

// Request interceptor: inject auth token
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

// Response interceptor: handle 401 globally
client.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('auth_token')
      // Only redirect if not already on a non-app page (avoid redirect loops in tests)
      if (typeof window !== 'undefined' && !window.location.pathname.includes('/login')) {
        window.dispatchEvent(new CustomEvent('auth:expired'))
      }
    }
    return Promise.reject(error)
  }
)

// ── Auth ───────────────────────────────────────────────────────────────────

export const authApi = {
  login(username, password) {
    // OAuth2 password flow: FastAPI expects form data
    const params = new URLSearchParams()
    params.append('username', username)
    params.append('password', password)
    return client.post('/api/auth/login', params, {
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' }
    })
  }
}

// ── Market ─────────────────────────────────────────────────────────────────

export const marketApi = {
  fetchData(ticker, period, interval) {
    return client.get('/api/market/fetch', {
      params: { ticker, period, interval }
    })
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
    })
  }
}

// ── Analysis ───────────────────────────────────────────────────────────────

export const analysisApi = {
  runAnalysis(ticker, period, interval) {
    return client.post('/api/analysis/run', { ticker, period, interval })
  },

  getHistory(ticker, limit = 10) {
    return client.get('/api/analysis/history', {
      params: { ticker, limit }
    })
  },

  getById(id) {
    return client.get(`/api/analysis/${id}`)
  }
}

// ── News ───────────────────────────────────────────────────────────────────

export const newsApi = {
  fetchNews(ticker) {
    return client.get('/api/news/fetch', { params: { ticker } })
  },

  getLatest(limit = 20) {
    return client.get('/api/news/latest', { params: { limit } })
  },

  getByTicker(symbol, limit = 20) {
    return client.get(`/api/news/ticker/${symbol}`, { params: { limit } })
  }
}

// ── Logs ───────────────────────────────────────────────────────────────────

export const logsApi = {
  getRecent(limit = 100) {
    return client.get('/api/logs/recent', { params: { limit } })
  }
}

// ── Health ─────────────────────────────────────────────────────────────────

export const healthApi = {
  check() {
    return client.get('/health')
  }
}

export default client
