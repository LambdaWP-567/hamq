/**
 * useApi — Axios instance with JWT auth header injection.
 *
 * Returns a memoized Axios instance that automatically attaches the
 * ``Authorization: Bearer <token>`` header to every request.
 *
 * Usage:
 *   const api = useApi(token)
 *   const status = await api.get<ProducerStatus>('/api/status')
 */

import { useMemo } from 'react'
import axios, { type AxiosInstance } from 'axios'

export function useApi(token: string | null): AxiosInstance {
  return useMemo(() => {
    const instance = axios.create({
      // All requests are relative to the current origin (Vite proxy handles dev)
      baseURL: '/',
      headers: {
        'Content-Type': 'application/json',
      },
    })

    // Request interceptor: inject Bearer token if available
    instance.interceptors.request.use((config) => {
      if (token) {
        config.headers['Authorization'] = `Bearer ${token}`
      }
      return config
    })

    // Response interceptor: convert 401 to a thrown error so callers can
    // react uniformly (e.g. redirect to login)
    instance.interceptors.response.use(
      (response) => response,
      (error) => {
        if (axios.isAxiosError(error) && error.response?.status === 401) {
          // Emit a custom event that App.tsx can listen to for global logout
          window.dispatchEvent(new CustomEvent('hamq:unauthorized'))
        }
        return Promise.reject(error)
      }
    )

    return instance
  }, [token])
}
