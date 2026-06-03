/**
 * App.tsx — Root application component for the HAMq Consumer UI.
 *
 * Responsibilities:
 *  - Owns auth state via useAuth
 *  - Provides the React Router tree
 *  - Handles global 401 events for forced logout
 *  - Renders LoginPage at /login and the protected Dashboard at /
 */

import React, { useEffect, useCallback, useState } from 'react'
import {
  BrowserRouter,
  Routes,
  Route,
  Navigate,
} from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import axios from 'axios'

import { useAuth } from './hooks/useAuth'
import type { LoginRequest } from './types'
import Dashboard from './components/Dashboard'

// ---------------------------------------------------------------------------
// Inline LoginPage (consumer-specific styling with consumer titles)
// ---------------------------------------------------------------------------
interface LoginPageProps {
  onLogin: (creds: LoginRequest) => Promise<boolean>
  loading: boolean
  error: string | null
}

function LoginPage({ onLogin, loading, error }: LoginPageProps) {
  const { t } = useTranslation()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [localError, setLocalError] = useState<string | null>(null)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setLocalError(null)
    const success = await onLogin({ username, password })
    if (!success) {
      setLocalError(t('login.error'))
    }
  }

  const displayError = error ?? localError

  return (
    <div className="min-h-screen flex flex-col items-center justify-center bg-gradient-to-br from-blue-700 to-blue-950 p-4">
      <div className="w-full max-w-sm">
        <div className="text-center mb-8">
          <h1 className="text-3xl font-bold text-white">{t('nav.title')}</h1>
          <p className="mt-2 text-blue-200 text-sm">{t('login.title')}</p>
        </div>

        <div className="bg-white dark:bg-gray-800 rounded-xl shadow-lg p-6">
          <h2 className="text-xl font-semibold text-gray-900 dark:text-white mb-6">
            {t('login.title')}
          </h2>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label htmlFor="username" className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                {t('login.username')}
              </label>
              <input
                id="username"
                type="text"
                autoComplete="username"
                required
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                disabled={loading}
                className="w-full rounded-lg border border-gray-300 dark:border-gray-600
                           bg-white dark:bg-gray-700 text-gray-900 dark:text-white
                           px-3 py-2 text-sm shadow-sm focus:outline-none
                           focus:ring-2 focus:ring-blue-500 disabled:opacity-60"
              />
            </div>

            <div>
              <label htmlFor="password" className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                {t('login.password')}
              </label>
              <input
                id="password"
                type="password"
                autoComplete="current-password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                disabled={loading}
                className="w-full rounded-lg border border-gray-300 dark:border-gray-600
                           bg-white dark:bg-gray-700 text-gray-900 dark:text-white
                           px-3 py-2 text-sm shadow-sm focus:outline-none
                           focus:ring-2 focus:ring-blue-500 disabled:opacity-60"
              />
            </div>

            {displayError && (
              <div className="rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
                {displayError}
              </div>
            )}

            <button
              type="submit"
              disabled={loading}
              className="w-full flex items-center justify-center gap-2 rounded-lg
                         bg-blue-600 hover:bg-blue-700 text-white text-sm font-semibold
                         px-4 py-2.5 transition-colors duration-150
                         disabled:opacity-60 disabled:cursor-not-allowed"
            >
              {loading && (
                <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" />
              )}
              {loading ? t('login.loading', { defaultValue: 'Logging in…' }) : t('login.submit')}
            </button>
          </form>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Protected route wrapper
// ---------------------------------------------------------------------------
interface ProtectedRouteProps {
  isAuthenticated: boolean
  children: React.ReactNode
}

function ProtectedRoute({ isAuthenticated, children }: ProtectedRouteProps) {
  if (!isAuthenticated) return <Navigate to="/login" replace />
  return <>{children}</>
}

// ---------------------------------------------------------------------------
// App
// ---------------------------------------------------------------------------
export default function App() {
  const { t } = useTranslation()
  const { token, login, logout, loading, error } = useAuth()

  const isAuthenticated = token !== null

  // Update document title
  useEffect(() => {
    document.title = t('nav.title')
  }, [t])

  // Intercept global 401s to force logout
  useEffect(() => {
    const interceptor = axios.interceptors.response.use(
      (response) => response,
      (err) => {
        if (axios.isAxiosError(err) && err.response?.status === 401) {
          logout()
        }
        return Promise.reject(err)
      }
    )
    return () => {
      axios.interceptors.response.eject(interceptor)
    }
  }, [logout])

  return (
    <BrowserRouter>
      <Routes>
        <Route
          path="/login"
          element={
            isAuthenticated ? (
              <Navigate to="/" replace />
            ) : (
              <LoginPage onLogin={login} loading={loading} error={error} />
            )
          }
        />
        <Route
          path="/"
          element={
            <ProtectedRoute isAuthenticated={isAuthenticated}>
              <Dashboard token={token} onLogout={logout} />
            </ProtectedRoute>
          }
        />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
