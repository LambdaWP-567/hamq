/**
 * LoginPage — Username/password form that authenticates against the arbiter backend.
 *
 * On success the JWT is stored via useAuth and the user is redirected to the
 * dashboard.  On failure, an inline error message is shown.
 */

import React, { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import type { useAuth } from '../hooks/useAuth'

interface LoginPageProps {
  onLogin: ReturnType<typeof useAuth>['login']
}

export default function LoginPage({ onLogin }: LoginPageProps) {
  const { t, i18n } = useTranslation()
  const navigate = useNavigate()

  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const currentLang = i18n.language.startsWith('de') ? 'de' : 'en'

  const toggleLanguage = () => {
    const next = currentLang === 'en' ? 'de' : 'en'
    i18n.changeLanguage(next)
    localStorage.setItem('hamq-arbiter-lang', next)
  }

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setError(null)
    setLoading(true)

    try {
      const success = await onLogin(username, password)
      if (success) {
        navigate('/', { replace: true })
      } else {
        setError(t('login.error'))
      }
    } catch {
      setError(t('login.error'))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex flex-col items-center justify-center bg-gradient-to-br from-brand-600 to-brand-900 p-4">
      {/* Language switcher */}
      <div className="absolute top-4 right-4">
        <button
          onClick={toggleLanguage}
          title={currentLang === 'en' ? 'Auf Deutsch wechseln' : 'Switch to English'}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium
                     bg-white/10 hover:bg-white/20 text-white border border-white/20
                     transition-colors duration-150"
          aria-label="Switch language"
        >
          {currentLang === 'en' ? (
            <span className="font-semibold">EN</span>
          ) : (
            <span className="font-semibold">DE</span>
          )}
        </button>
      </div>

      <div className="w-full max-w-sm">
        {/* Logo / title */}
        <div className="text-center mb-8">
          {/* Arbiter icon */}
          <div className="mx-auto mb-4 w-16 h-16 rounded-2xl bg-white/20 flex items-center justify-center">
            <svg className="w-9 h-9 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round"
                d="M9 12.75L11.25 15 15 9.75m-3-7.036A11.959 11.959 0 013.598 6 11.99 11.99 0 003 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285z" />
            </svg>
          </div>
          <h1 className="text-3xl font-bold text-white">{t('nav.title')}</h1>
          <p className="mt-2 text-brand-200 text-sm">{t('login.welcome')}</p>
        </div>

        {/* Login card */}
        <div className="card">
          <h2 className="text-xl font-semibold text-gray-900 mb-6">{t('login.title')}</h2>

          <form onSubmit={handleSubmit} className="space-y-4">
            {/* Username */}
            <div>
              <label
                htmlFor="username"
                className="block text-sm font-medium text-gray-700 mb-1"
              >
                {t('login.username')}
              </label>
              <input
                id="username"
                type="text"
                autoComplete="username"
                required
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                className="input"
                disabled={loading}
                placeholder="admin"
              />
            </div>

            {/* Password */}
            <div>
              <label
                htmlFor="password"
                className="block text-sm font-medium text-gray-700 mb-1"
              >
                {t('login.password')}
              </label>
              <input
                id="password"
                type="password"
                autoComplete="current-password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="input"
                disabled={loading}
                placeholder="••••••••"
              />
            </div>

            {/* Error message */}
            {error && (
              <div className="rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
                {error}
              </div>
            )}

            {/* Submit */}
            <button
              type="submit"
              disabled={loading || !username || !password}
              className="btn-primary w-full"
            >
              {loading && (
                <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" />
              )}
              {loading ? t('login.submitting') : t('login.submit')}
            </button>
          </form>
        </div>
      </div>
    </div>
  )
}
