/**
 * useAuth — JWT authentication state hook for HAMq Arbiter.
 *
 * Stores the JWT token in localStorage so that the session survives page
 * reloads.  Provides login(), logout(), and the current token.
 */

import { useState, useCallback } from 'react'
import axios from 'axios'
import type { TokenResponse } from '../types'

const TOKEN_KEY = 'hamq-arbiter-token'

export function useAuth() {
  // Initialise from localStorage so the user stays logged in on refresh
  const [token, setToken] = useState<string | null>(
    () => localStorage.getItem(TOKEN_KEY)
  )

  /**
   * Attempt to authenticate with the arbiter backend.
   *
   * @returns true on success, false on invalid credentials
   * @throws on unexpected network errors
   */
  const login = useCallback(
    async (username: string, password: string): Promise<boolean> => {
      try {
        const response = await axios.post<TokenResponse>(
          '/api/auth/login',
          { username, password }
        )
        const jwt = response.data.access_token
        localStorage.setItem(TOKEN_KEY, jwt)
        setToken(jwt)
        return true
      } catch (err) {
        if (axios.isAxiosError(err) && err.response?.status === 401) {
          // Invalid credentials — caller shows an error message
          return false
        }
        // Re-throw unexpected errors (network down, server error, etc.)
        throw err
      }
    },
    []
  )

  /** Clear the stored token and return to login. */
  const logout = useCallback(() => {
    localStorage.removeItem(TOKEN_KEY)
    setToken(null)
  }, [])

  return { token, login, logout, isAuthenticated: token !== null }
}
