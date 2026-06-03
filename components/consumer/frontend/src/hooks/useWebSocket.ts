/**
 * useWebSocket — connects to the /ws endpoint and delivers StatusUpdate objects.
 *
 * The WebSocket URL is constructed from the current page origin so it works
 * both in development (proxied by Vite) and in production (same host).
 *
 * The hook automatically reconnects on disconnect with exponential back-off.
 */

import { useEffect, useRef, useState, useCallback } from 'react'
import type { StatusUpdate } from '../types'

interface UseWebSocketOptions {
  token: string | null
  /** Called each time a StatusUpdate message arrives. */
  onMessage: (update: StatusUpdate) => void
}

export function useWebSocket({ token, onMessage }: UseWebSocketOptions) {
  const wsRef = useRef<WebSocket | null>(null)
  const [connected, setConnected] = useState(false)
  const reconnectDelay = useRef(1000)
  const mountedRef = useRef(true)

  const connect = useCallback(() => {
    if (!token || !mountedRef.current) return

    // Build the WebSocket URL — replace http(s) with ws(s).
    const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const url = `${protocol}://${window.location.host}/ws?token=${encodeURIComponent(token)}`

    const ws = new WebSocket(url)
    wsRef.current = ws

    ws.onopen = () => {
      setConnected(true)
      reconnectDelay.current = 1000 // reset back-off
    }

    ws.onmessage = (event: MessageEvent) => {
      try {
        const update: StatusUpdate = JSON.parse(event.data as string)
        onMessage(update)
      } catch {
        // Ignore malformed messages.
      }
    }

    ws.onclose = () => {
      setConnected(false)
      if (mountedRef.current) {
        // Exponential back-off capped at 16 s.
        const delay = reconnectDelay.current
        reconnectDelay.current = Math.min(delay * 2, 16000)
        setTimeout(connect, delay)
      }
    }

    ws.onerror = () => {
      ws.close()
    }
  }, [token, onMessage])

  useEffect(() => {
    mountedRef.current = true
    connect()
    return () => {
      mountedRef.current = false
      wsRef.current?.close()
    }
  }, [connect])

  return { connected }
}
