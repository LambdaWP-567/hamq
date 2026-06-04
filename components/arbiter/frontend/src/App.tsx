/**
 * HAMq Arbiter — Root application component.
 *
 * Sets up React Router with two routes:
 *   /login  → LoginPage (public)
 *   /       → Dashboard (protected — redirects to /login if no token)
 *
 * Also listens for the custom `hamq:unauthorized` event from the Axios
 * interceptor to perform a global logout on 401 responses.
 */

import React, { useEffect } from 'react'
import {
  BrowserRouter,
  Routes,
  Route,
  Navigate,
  useNavigate,
} from 'react-router-dom'
import { useAuth } from './hooks/useAuth'
import LoginPage from './components/LoginPage'
import Dashboard from './components/Dashboard'

// ---------------------------------------------------------------------------
// ProtectedRoute — redirects unauthenticated users to /login
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
// AppRoutes — inner component that has access to the router context
// ---------------------------------------------------------------------------

function AppRoutes() {
  const { token, login, logout, isAuthenticated } = useAuth()
  const navigate = useNavigate()

  // Listen for 401 responses emitted by the Axios interceptor
  useEffect(() => {
    const handleUnauthorized = () => {
      logout()
      navigate('/login', { replace: true })
    }
    window.addEventListener('hamq:unauthorized', handleUnauthorized)
    return () => {
      window.removeEventListener('hamq:unauthorized', handleUnauthorized)
    }
  }, [logout, navigate])

  return (
    <Routes>
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
      <Route
        path="/"
        element={
          <ProtectedRoute isAuthenticated={isAuthenticated}>
            <Dashboard token={token} onLogout={logout} />
          </ProtectedRoute>
        }
      />
      {/* Catch-all: redirect unknown paths to dashboard */}
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

// ---------------------------------------------------------------------------
// App — root component with BrowserRouter
// ---------------------------------------------------------------------------

export default function App() {
  return (
    <BrowserRouter>
      <AppRoutes />
    </BrowserRouter>
  )
}
