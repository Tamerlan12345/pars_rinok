import { useState, useEffect, useCallback } from 'react'
import { healthApi } from '../api/client.js'

const VIEWS = [
  { id: 'dashboard', label: 'Dashboard',  icon: '⬡' },
  { id: 'analysis',  label: 'Analysis',   icon: '◈' },
  { id: 'news',      label: 'News',       icon: '◎' },
  { id: 'logs',      label: 'Logs',       icon: '▤' }
]

function LogoMark() {
  return (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 220 60" fill="none" style={{ height: '32px', width: 'auto' }}>
      <defs>
        <linearGradient id="lgNav" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor="#6366f1"/>
          <stop offset="100%" stopColor="#06b6d4"/>
        </linearGradient>
        <linearGradient id="tgNav" x1="0%" y1="0%" x2="100%" y2="0%">
          <stop offset="0%" stopColor="#6366f1"/>
          <stop offset="100%" stopColor="#06b6d4"/>
        </linearGradient>
      </defs>
      <line x1="20" y1="10" x2="35" y2="8" stroke="url(#lgNav)" strokeWidth="1.5" strokeOpacity="0.7"/>
      <line x1="20" y1="10" x2="12" y2="28" stroke="url(#lgNav)" strokeWidth="1.5" strokeOpacity="0.7"/>
      <line x1="12" y1="28" x2="20" y2="46" stroke="url(#lgNav)" strokeWidth="1.5" strokeOpacity="0.7"/>
      <line x1="20" y1="46" x2="35" y2="48" stroke="url(#lgNav)" strokeWidth="1.5" strokeOpacity="0.7"/>
      <circle cx="20" cy="10" r="5" fill="url(#lgNav)"/>
      <circle cx="35" cy="8" r="4" fill="url(#lgNav)" fillOpacity="0.85"/>
      <circle cx="12" cy="28" r="5" fill="url(#lgNav)"/>
      <circle cx="20" cy="46" r="5" fill="url(#lgNav)"/>
      <circle cx="35" cy="48" r="4" fill="url(#lgNav)" fillOpacity="0.85"/>
      <circle cx="20" cy="10" r="2.5" fill="white" fillOpacity="0.5"/>
      <circle cx="12" cy="28" r="2.5" fill="white" fillOpacity="0.5"/>
      <circle cx="20" cy="46" r="2.5" fill="white" fillOpacity="0.5"/>
      <text x="52" y="30" fontFamily="Inter, sans-serif" fontSize="24" fontWeight="700" letterSpacing="-0.5" fill="url(#tgNav)">centras</text>
      <text x="52" y="46" fontFamily="Inter, sans-serif" fontSize="12" fontWeight="400" letterSpacing="2" fill="#06b6d4" fillOpacity="0.9">tokenizer</text>
    </svg>
  )
}

export default function Navbar({ currentView, setCurrentView, onLogout }) {
  const [healthStatus, setHealthStatus] = useState('checking') // 'online' | 'offline' | 'checking'

  const checkHealth = useCallback(async () => {
    try {
      await healthApi.check()
      setHealthStatus('online')
    } catch {
      setHealthStatus('offline')
    }
  }, [])

  useEffect(() => {
    checkHealth()
    const interval = setInterval(checkHealth, 30_000)
    return () => clearInterval(interval)
  }, [checkHealth])

  const healthLabel = {
    online:   'Backend Online',
    offline:  'Backend Offline',
    checking: 'Checking…'
  }[healthStatus]

  return (
    <nav style={{
      position: 'fixed',
      top: 0,
      left: 0,
      right: 0,
      height: 'var(--navbar-height)',
      background: 'rgba(10, 14, 26, 0.85)',
      backdropFilter: 'blur(20px)',
      WebkitBackdropFilter: 'blur(20px)',
      borderBottom: '1px solid var(--glass-border)',
      zIndex: 1000,
      display: 'flex',
      alignItems: 'center',
      padding: '0 24px',
      gap: '24px'
    }}>
      {/* Left: Logo */}
      <div style={{ display: 'flex', alignItems: 'center', flexShrink: 0 }}>
        <LogoMark />
      </div>

      {/* Center: Nav tabs */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        gap: '4px',
        flex: 1,
        justifyContent: 'center'
      }}>
        {VIEWS.map(view => {
          const isActive = currentView === view.id
          return (
            <button
              key={view.id}
              onClick={() => setCurrentView(view.id)}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
                padding: '8px 16px',
                borderRadius: '8px',
                fontSize: '14px',
                fontWeight: isActive ? '600' : '400',
                color: isActive ? 'var(--text-primary)' : 'var(--text-secondary)',
                background: isActive ? 'rgba(99,102,241,0.12)' : 'transparent',
                border: 'none',
                cursor: 'pointer',
                position: 'relative',
                transition: 'all 0.15s ease',
                fontFamily: 'inherit'
              }}
              onMouseEnter={e => {
                if (!isActive) e.currentTarget.style.color = 'var(--text-primary)'
              }}
              onMouseLeave={e => {
                if (!isActive) e.currentTarget.style.color = 'var(--text-secondary)'
              }}
            >
              <span style={{ fontSize: '16px', opacity: 0.8 }}>{view.icon}</span>
              {view.label}
              {isActive && (
                <span style={{
                  position: 'absolute',
                  bottom: '-1px',
                  left: '16px',
                  right: '16px',
                  height: '2px',
                  background: 'var(--accent-gradient)',
                  borderRadius: '2px 2px 0 0'
                }} />
              )}
            </button>
          )
        })}
      </div>

      {/* Right: health + logout */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flexShrink: 0 }}>
        {/* Health indicator */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <span className={`status-dot ${healthStatus}`} />
          <span style={{ fontSize: '12px', color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>
            {healthLabel}
          </span>
        </div>

        {/* Divider */}
        <div style={{ width: '1px', height: '20px', background: 'var(--glass-border)' }} />

        {/* Logout */}
        <button
          className="btn btn-ghost btn-sm"
          onClick={onLogout}
          title="Sign out"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/>
            <polyline points="16 17 21 12 16 7"/>
            <line x1="21" y1="12" x2="9" y2="12"/>
          </svg>
          Sign out
        </button>
      </div>
    </nav>
  )
}
