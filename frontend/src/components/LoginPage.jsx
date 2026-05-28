import { useState, useRef } from 'react'
import { authApi } from '../api/client.js'

// Animated background orb — pure CSS, no JS movement
function BackgroundOrbs() {
  return (
    <div style={{
      position: 'fixed',
      inset: 0,
      overflow: 'hidden',
      pointerEvents: 'none',
      zIndex: 0
    }}>
      <div style={{
        position: 'absolute',
        top: '-15%',
        left: '-10%',
        width: '500px',
        height: '500px',
        borderRadius: '50%',
        background: 'radial-gradient(circle, rgba(99,102,241,0.18) 0%, transparent 70%)',
        animation: 'orb-drift 18s ease-in-out infinite'
      }} />
      <div style={{
        position: 'absolute',
        bottom: '-20%',
        right: '-10%',
        width: '600px',
        height: '600px',
        borderRadius: '50%',
        background: 'radial-gradient(circle, rgba(6,182,212,0.14) 0%, transparent 70%)',
        animation: 'orb-drift 24s ease-in-out infinite reverse'
      }} />
      <div style={{
        position: 'absolute',
        top: '40%',
        left: '50%',
        width: '300px',
        height: '300px',
        borderRadius: '50%',
        background: 'radial-gradient(circle, rgba(139,92,246,0.1) 0%, transparent 70%)',
        transform: 'translateX(-50%)',
        animation: 'orb-drift 14s ease-in-out infinite'
      }} />
      {/* Particle dots */}
      {[...Array(20)].map((_, i) => (
        <div key={i} style={{
          position: 'absolute',
          width: Math.random() * 3 + 1 + 'px',
          height: Math.random() * 3 + 1 + 'px',
          borderRadius: '50%',
          background: i % 3 === 0 ? 'rgba(99,102,241,0.6)' : i % 3 === 1 ? 'rgba(6,182,212,0.5)' : 'rgba(139,92,246,0.5)',
          top: (i * 37 + 5) % 95 + '%',
          left: (i * 53 + 7) % 95 + '%',
          animation: `float ${6 + (i % 5) * 2}s ease-in-out infinite`,
          animationDelay: `${i * 0.4}s`
        }} />
      ))}
    </div>
  )
}

// Inline SVG logo for the login page
function LogoMark() {
  return (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 220 60" fill="none" style={{ height: '48px', width: 'auto' }}>
      <defs>
        <linearGradient id="lgLogin" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor="#6366f1"/>
          <stop offset="100%" stopColor="#06b6d4"/>
        </linearGradient>
        <linearGradient id="tgLogin" x1="0%" y1="0%" x2="100%" y2="0%">
          <stop offset="0%" stopColor="#6366f1"/>
          <stop offset="100%" stopColor="#06b6d4"/>
        </linearGradient>
      </defs>
      <line x1="20" y1="10" x2="35" y2="8" stroke="url(#lgLogin)" strokeWidth="1.5" strokeOpacity="0.7"/>
      <line x1="20" y1="10" x2="12" y2="28" stroke="url(#lgLogin)" strokeWidth="1.5" strokeOpacity="0.7"/>
      <line x1="12" y1="28" x2="20" y2="46" stroke="url(#lgLogin)" strokeWidth="1.5" strokeOpacity="0.7"/>
      <line x1="20" y1="46" x2="35" y2="48" stroke="url(#lgLogin)" strokeWidth="1.5" strokeOpacity="0.7"/>
      <circle cx="20" cy="10" r="5" fill="url(#lgLogin)"/>
      <circle cx="35" cy="8" r="4" fill="url(#lgLogin)" fillOpacity="0.85"/>
      <circle cx="12" cy="28" r="5" fill="url(#lgLogin)"/>
      <circle cx="20" cy="46" r="5" fill="url(#lgLogin)"/>
      <circle cx="35" cy="48" r="4" fill="url(#lgLogin)" fillOpacity="0.85"/>
      <circle cx="20" cy="10" r="2.5" fill="white" fillOpacity="0.5"/>
      <circle cx="12" cy="28" r="2.5" fill="white" fillOpacity="0.5"/>
      <circle cx="20" cy="46" r="2.5" fill="white" fillOpacity="0.5"/>
      <text x="52" y="30" fontFamily="Inter, sans-serif" fontSize="24" fontWeight="700" letterSpacing="-0.5" fill="url(#tgLogin)">centras</text>
      <text x="52" y="46" fontFamily="Inter, sans-serif" fontSize="12" fontWeight="400" letterSpacing="2" fill="#06b6d4" fillOpacity="0.9">tokenizer</text>
    </svg>
  )
}

export default function LoginPage({ setToken }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const passwordRef = useRef(null)

  async function handleSubmit(e) {
    e.preventDefault()
    if (!username.trim() || !password) return

    setError('')
    setLoading(true)
    try {
      const res = await authApi.login(username.trim(), password)
      const t = res.data?.access_token || res.data?.token
      if (!t) throw new Error('No token in server response')
      setToken(t)
    } catch (err) {
      const msg =
        err.response?.data?.detail ||
        err.response?.data?.message ||
        err.message ||
        'Login failed. Check credentials and try again.'
      setError(msg)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{
      position: 'relative',
      minHeight: '100vh',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      background: 'var(--bg-primary)',
      padding: '24px'
    }}>
      <BackgroundOrbs />

      <div style={{ position: 'relative', zIndex: 1, width: '100%', maxWidth: '420px', animation: 'slideInUp 0.4s ease' }}>
        {/* Card */}
        <div className="glass-card-elevated" style={{ padding: '40px 36px 36px' }}>
          {/* Logo */}
          <div style={{ display: 'flex', justifyContent: 'center', marginBottom: '8px' }}>
            <LogoMark />
          </div>

          {/* Tagline */}
          <p style={{
            textAlign: 'center',
            fontSize: '13px',
            color: 'var(--text-muted)',
            letterSpacing: '0.1em',
            textTransform: 'uppercase',
            marginBottom: '36px'
          }}>
            Financial Intelligence Platform
          </p>

          {/* Form */}
          <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            <div className="form-group">
              <label className="input-label" htmlFor="login-username">Username</label>
              <input
                id="login-username"
                className="input-field"
                type="text"
                placeholder="Enter your username"
                value={username}
                onChange={e => setUsername(e.target.value)}
                autoComplete="username"
                autoFocus
                disabled={loading}
                onKeyDown={e => e.key === 'Enter' && passwordRef.current?.focus()}
              />
            </div>

            <div className="form-group">
              <label className="input-label" htmlFor="login-password">Password</label>
              <input
                id="login-password"
                className="input-field"
                type="password"
                placeholder="Enter your password"
                value={password}
                onChange={e => setPassword(e.target.value)}
                autoComplete="current-password"
                ref={passwordRef}
                disabled={loading}
              />
            </div>

            {error && (
              <div className="alert alert-error" style={{ animation: 'fadeIn 0.2s ease' }}>
                <span style={{ fontSize: '16px' }}>⚠</span>
                <span>{error}</span>
              </div>
            )}

            <button
              type="submit"
              className={`btn btn-primary btn-lg w-full${loading ? ' btn-loading' : ''}`}
              disabled={loading || !username.trim() || !password}
              style={{ marginTop: '4px' }}
            >
              {loading ? '' : 'Sign In'}
            </button>
          </form>

          {/* Footer */}
          <p style={{
            textAlign: 'center',
            marginTop: '24px',
            fontSize: '12px',
            color: 'var(--text-muted)'
          }}>
            Centras Tokenizer v1.0 · AI-powered market analysis
          </p>
        </div>

        {/* Decorative bottom line */}
        <div style={{
          height: '2px',
          background: 'var(--accent-gradient)',
          borderRadius: '0 0 16px 16px',
          opacity: 0.6,
          marginTop: '-2px'
        }} />
      </div>
    </div>
  )
}
