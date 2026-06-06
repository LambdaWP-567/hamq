import React from 'react'
import { useAuth } from './hooks/useAuth'
import LoginPage from './components/LoginPage'
import Dashboard from './components/Dashboard'

export default function App() {
  const { token, login, logout, isAuthenticated } = useAuth()

  if (!isAuthenticated) {
    return <LoginPage onLogin={login} />
  }

  return <Dashboard token={token!} onLogout={logout} />
}
