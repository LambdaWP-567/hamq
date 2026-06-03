import React, { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { AlertCircle, Lock, User, Zap } from 'lucide-react'
import clsx from 'clsx'
import { useAuth } from '../hooks/useAuth'

interface LoginPageProps {
  onLogin?: () => void
}

const LoginPage: React.FC<LoginPageProps> = ({ onLogin }) => {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const { login } = useAuth()

  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleSubmit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    setError(null)
    setLoading(true)

    try {
      await login({ username, password })
      onLogin?.()
      navigate('/', { replace: true })
    } catch (err) {
      const msg = err instanceof Error ? err.message : t('auth.loginError')
      // Map 401 detail to friendly message
      setError(
        msg.toLowerCase().includes('incorrect') || msg.toLowerCase().includes('unauthorized')
          ? t('auth.invalidCredentials')
          : t('auth.loginError')
      )
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-gray-950 via-blue-950 to-gray-900 px-4">
      {/* Background grid pattern */}
      <div
        className="absolute inset-0 opacity-10"
        style={{
          backgroundImage:
            'linear-gradient(rgba(59,130,246,0.3) 1px, transparent 1px), linear-gradient(90deg, rgba(59,130,246,0.3) 1px, transparent 1px)',
          backgroundSize: '40px 40px',
        }}
      />

      <div className="relative w-full max-w-md">
        {/* Logo / branding */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-blue-600 shadow-lg shadow-blue-600/30 mb-4">
            <Zap className="w-8 h-8 text-white" />
          </div>
          <h1 className="text-3xl font-bold text-white tracking-tight">HAMq Controller</h1>
          <p className="mt-2 text-blue-200/70 text-sm">
            {t('app.description')}
          </p>
        </div>

        {/* Card */}
        <div className="bg-gray-900/80 backdrop-blur-xl rounded-2xl shadow-2xl border border-white/10 p-8">
          <h2 className="text-lg font-semibold text-white mb-6">{t('auth.login')}</h2>

          {error && (
            <div className="mb-4 flex items-start gap-3 p-3 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400 text-sm">
              <AlertCircle className="w-4 h-4 mt-0.5 flex-shrink-0" />
              <span>{error}</span>
            </div>
          )}

          <form onSubmit={(e) => void handleSubmit(e)} className="space-y-4">
            {/* Username */}
            <div>
              <label
                htmlFor="username"
                className="block text-sm font-medium text-gray-300 mb-1.5"
              >
                {t('auth.username')}
              </label>
              <div className="relative">
                <User className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500" />
                <input
                  id="username"
                  type="text"
                  autoComplete="username"
                  required
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  disabled={loading}
                  className={clsx(
                    'w-full pl-10 pr-4 py-2.5 rounded-lg text-sm',
                    'bg-gray-800 border border-gray-700 text-white placeholder-gray-500',
                    'focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent',
                    'disabled:opacity-50 disabled:cursor-not-allowed',
                    'transition-colors'
                  )}
                  placeholder="admin"
                />
              </div>
            </div>

            {/* Password */}
            <div>
              <label
                htmlFor="password"
                className="block text-sm font-medium text-gray-300 mb-1.5"
              >
                {t('auth.password')}
              </label>
              <div className="relative">
                <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500" />
                <input
                  id="password"
                  type="password"
                  autoComplete="current-password"
                  required
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  disabled={loading}
                  className={clsx(
                    'w-full pl-10 pr-4 py-2.5 rounded-lg text-sm',
                    'bg-gray-800 border border-gray-700 text-white placeholder-gray-500',
                    'focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent',
                    'disabled:opacity-50 disabled:cursor-not-allowed',
                    'transition-colors'
                  )}
                  placeholder="••••••••"
                />
              </div>
            </div>

            <button
              type="submit"
              disabled={loading || !username || !password}
              className={clsx(
                'w-full py-2.5 px-4 rounded-lg text-sm font-semibold text-white',
                'bg-blue-600 hover:bg-blue-500',
                'focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 focus:ring-offset-gray-900',
                'disabled:opacity-50 disabled:cursor-not-allowed',
                'transition-colors duration-150',
                'mt-2'
              )}
            >
              {loading ? t('auth.loggingIn') : t('auth.loginButton')}
            </button>
          </form>
        </div>

        <p className="text-center mt-6 text-gray-600 text-xs">
          HAMq Controller v1.0.0 — Chaos Engineering Platform
        </p>
      </div>
    </div>
  )
}

export default LoginPage
