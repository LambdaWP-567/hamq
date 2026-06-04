import { useState, useCallback, useEffect } from 'react'
import type { AuthToken, LoginRequest } from '../types'

const TOKEN_KEY = 'hamq_controller_token'
const USERNAME_KEY = 'hamq_controller_username'

export interface AuthState {
  token: string | null
  username: string | null
  isAuthenticated: boolean
  login: (credentials: LoginRequest) => Promise<void>
  logout: () => void
}

export function useAuth(): AuthState {
  const [token, setToken] = useState<string | null>(() =>
    localStorage.getItem(TOKEN_KEY)
  )
  const [username, setUsername] = useState<string | null>(() =>
    localStorage.getItem(USERNAME_KEY)
  )

  // Validate token on mount: decode the JWT and check expiry
  useEffect(() => {
    if (!token) return

    try {
      // JWT is base64url-encoded: split and decode the payload section
      const parts = token.split('.')
      if (parts.length !== 3) throw new Error('malformed token')

      const payload = JSON.parse(atob(parts[1]!.replace(/-/g, '+').replace(/_/g, '/')))
      const expiry: number = payload.exp ?? 0

      if (expiry * 1000 < Date.now()) {
        // Token has expired — clear it immediately
        setToken(null)
        setUsername(null)
        localStorage.removeItem(TOKEN_KEY)
        localStorage.removeItem(USERNAME_KEY)
      }
    } catch {
      // Unparseable token — treat as invalid
      setToken(null)
      setUsername(null)
      localStorage.removeItem(TOKEN_KEY)
      localStorage.removeItem(USERNAME_KEY)
    }
  }, [token])

  const login = useCallback(async (credentials: LoginRequest): Promise<void> => {
    const response = await fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(credentials),
    })

    if (!response.ok) {
      const body: unknown = await response.json().catch(() => ({}))
      const detail = (body as Record<string, string>)['detail'] ?? 'Authentication failed'
      throw new Error(detail)
    }

    const data = (await response.json()) as AuthToken
    localStorage.setItem(TOKEN_KEY, data.access_token)
    localStorage.setItem(USERNAME_KEY, credentials.username)
    setToken(data.access_token)
    setUsername(credentials.username)
  }, [])

  const logout = useCallback(() => {
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(USERNAME_KEY)
    setToken(null)
    setUsername(null)
  }, [])

  return {
    token,
    username,
    isAuthenticated: token !== null,
    login,
    logout,
  }
}
