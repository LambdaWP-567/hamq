/**
 * App.tsx — Root application component for the HAMq Producer UI.
 *
 * Responsibilities:
 *  - Owns auth state (token, user info) via useAuth
 *  - Provides the React Router tree
 *  - Listens for the global `hamq:unauthorized` event to force logout
 *  - Renders LoginPage at /login and the protected Dashboard at /
 */

import React, { useEffect, useCallback } from 'react'
import {
  BrowserRouter,
  Routes,
  Route,
  Navigate,
} from 'react-router-dom'
import { useTranslation } from 'react-i18next'

import { useAuth } from './hooks/useAuth'
import { useApi } from './hooks/useApi'
import LoginPage from './components/LoginPage'
import Dashboard from './components/Dashboard'

// ---------------------------------------------------------------------------
// Protected route wrapper
// ---------------------------------------------------------------------------
interface ProtectedRouteProps {
  isAuthenticated: boolean
  children: React.ReactNode
}

function ProtectedRoute({ isAuthenticated, children }: ProtectedRouteProps) {
  if (!isAuthenticated) {
    return <Navigate to="/login" replace />
  }
  return <>{children}</>
}

// ---------------------------------------------------------------------------
// App
// ---------------------------------------------------------------------------
export default function App() {
  const { t } = useTranslation()
  const { token, login, logout, isAuthenticated } = useAuth()
  const api = useApi(token)

  // Global logout on 401 response (emitted by useApi interceptor)
  const handleUnauthorized = useCallback(() => {
    logout()
  }, [logout])

  useEffect(() => {
    window.addEventListener('hamq:unauthorized', handleUnauthorized)
    return () => {
      window.removeEventListener('hamq:unauthorized', handleUnauthorized)
    }
  }, [handleUnauthorized])

  // Update page title based on auth state
  useEffect(() => {
    document.title = t('nav.title')
  }, [t])

  return (
    <BrowserRouter>
      <Routes>
        {/* Public route — login */}
        <Route
          path="/login"
          element={
            isAuthenticated ? (
              <Navigate to="/" replace />
            ) : (
              <LoginPage onLogin={login} />
            )
          }
        />

        {/* Protected route — dashboard */}
        <Route
          path="/"
          element={
            <ProtectedRoute isAuthenticated={isAuthenticated}>
              <Dashboard token={token} api={api} onLogout={logout} />
            </ProtectedRoute>
          }
        />

        {/* Catch-all redirect */}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
