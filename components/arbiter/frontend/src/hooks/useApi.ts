/**
 * useApi — Axios instance with JWT auth header injection for HAMq Arbiter.
 *
 * Returns a memoized Axios instance that automatically attaches the
 * `Authorization: Bearer <token>` header to every request.
 *
 * Usage:
 *   const api = useApi(token)
 *   const status = await api.get<ArbiterStatus>('/api/status')
 */

import { useMemo } from 'react'
import axios, { type AxiosInstance } from 'axios'

export function useApi(token: string | null): AxiosInstance {
  return useMemo(() => {
    const baseURL = import.meta.env.VITE_API_URL as string | undefined

    const instance = axios.create({
      baseURL: baseURL ?? '/',
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

    // Response interceptor: convert 401 to a custom event so App.tsx can
    // perform a global logout without prop-drilling
    instance.interceptors.response.use(
      (response) => response,
      (error) => {
        if (axios.isAxiosError(error) && error.response?.status === 401) {
          window.dispatchEvent(new CustomEvent('hamq:unauthorized'))
        }
        return Promise.reject(error)
      }
    )

    return instance
  }, [token])
}
