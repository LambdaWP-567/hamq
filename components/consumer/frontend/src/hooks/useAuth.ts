/**
 * useAuth — authentication state hook.
 *
 * Stores the JWT in localStorage under 'hamq-consumer-token'.
 * Provides login / logout helpers and the current token.
 */

import { useState, useCallback } from 'react'
import axios from 'axios'
import type { LoginRequest, TokenResponse } from '../types'

const TOKEN_KEY = 'hamq-consumer-token'

export function useAuth() {
  const [token, setToken] = useState<string | null>(
    () => localStorage.getItem(TOKEN_KEY)
  )
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  /**
   * Authenticate against POST /api/auth/login.
   * On success the JWT is persisted and returned.
   */
  const login = useCallback(async (creds: LoginRequest): Promise<boolean> => {
    setLoading(true)
    setError(null)
    try {
      const resp = await axios.post<TokenResponse>('/api/auth/login', creds)
      const { access_token } = resp.data
      localStorage.setItem(TOKEN_KEY, access_token)
      setToken(access_token)
      return true
    } catch {
      setError('Invalid credentials')
      return false
    } finally {
      setLoading(false)
    }
  }, [])

  /** Clear the stored token and force re-login. */
  const logout = useCallback(() => {
    localStorage.removeItem(TOKEN_KEY)
    setToken(null)
  }, [])

  return { token, login, logout, loading, error }
}
