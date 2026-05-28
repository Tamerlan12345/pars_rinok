import { useState, useEffect, useCallback } from 'react'
import LoginPage from './components/LoginPage.jsx'
import Navbar from './components/Navbar.jsx'
import Dashboard from './components/Dashboard.jsx'
import AIAnalysisPanel from './components/AIAnalysisPanel.jsx'
import NewsPanel from './components/NewsPanel.jsx'
import LogsPanel from './components/LogsPanel.jsx'

const VIEWS = {
  dashboard: Dashboard,
  analysis: AIAnalysisPanel,
  news: NewsPanel,
  logs: LogsPanel
}

export default function App() {
  const [token, setToken] = useState(() => localStorage.getItem('auth_token'))
  const [currentView, setCurrentView] = useState('dashboard')

  // Listen for auth expiry fired by the API interceptor
  useEffect(() => {
    const handleAuthExpired = () => {
      setToken(null)
    }
    window.addEventListener('auth:expired', handleAuthExpired)
    return () => window.removeEventListener('auth:expired', handleAuthExpired)
  }, [])

  const handleSetToken = useCallback((newToken) => {
    if (newToken) {
      localStorage.setItem('auth_token', newToken)
    } else {
      localStorage.removeItem('auth_token')
    }
    setToken(newToken)
  }, [])

  const handleLogout = useCallback(() => {
    handleSetToken(null)
    setCurrentView('dashboard')
  }, [handleSetToken])

  const isAuthenticated = Boolean(token)

  if (!isAuthenticated) {
    return <LoginPage setToken={handleSetToken} />
  }

  const ViewComponent = VIEWS[currentView] || Dashboard

  return (
    <div className="page-wrapper">
      <Navbar
        currentView={currentView}
        setCurrentView={setCurrentView}
        onLogout={handleLogout}
      />
      <main className="main-content animate-fade-in">
        <ViewComponent />
      </main>
    </div>
  )
}
