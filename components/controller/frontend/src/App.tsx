/**
 * App.tsx — Root component for the HAMq Controller UI.
 *
 * Routes:
 *   /login  — LoginPage (public)
 *   /       — Dashboard (protected, requires JWT)
 *
 * Auth events: a global 'hamq:unauthorized' event (dispatched by useApi on 401)
 * forces logout and redirect to /login without requiring prop drilling.
 */

import React, { useEffect } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { useAuth } from './hooks/useAuth'
import LoginPage from './components/LoginPage'
import Dashboard from './components/Dashboard'

/** Wrap a route so unauthenticated visitors are redirected to /login. */
const ProtectedRoute: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { isAuthenticated } = useAuth()
  return isAuthenticated ? <>{children}</> : <Navigate to="/login" replace />
}

const App: React.FC = () => {
  const { logout } = useAuth()

  // Listen for 401 events emitted by the Axios interceptor in useApi.ts
  useEffect(() => {
    const handle = () => logout()
    window.addEventListener('hamq:unauthorized', handle)
    return () => window.removeEventListener('hamq:unauthorized', handle)
  }, [logout])

  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route
          path="/"
          element={
            <ProtectedRoute>
              <Dashboard />
            </ProtectedRoute>
          }
        />
        {/* Catch-all: redirect unknown paths to root */}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}

export default App
