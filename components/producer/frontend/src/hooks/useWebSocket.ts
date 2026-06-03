/**
 * useWebSocket — auto-reconnecting WebSocket hook for real-time status.
 *
 * Connects to the backend /ws endpoint, authenticates via query-param JWT,
 * and calls onMessage() for each received status update.
 * Reconnects automatically after a configurable delay.
 */

import { useEffect, useRef, useCallback } from 'react'

const RECONNECT_DELAY_MS = 3000

interface UseWebSocketOptions {
  /** JWT bearer token (null = do not connect) */
  token: string | null
  /** Called with the parsed JSON payload for each server message */
  onMessage: (data: unknown) => void
  /** Called when the connection state changes */
  onConnectionChange?: (connected: boolean) => void
}

export function useWebSocket({
  token,
  onMessage,
  onConnectionChange,
}: UseWebSocketOptions) {
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  // Stable refs so we don't need these in the effect dependency array
  const onMessageRef = useRef(onMessage)
  const onConnectionChangeRef = useRef(onConnectionChange)

  // Keep refs up-to-date without triggering reconnects
  useEffect(() => { onMessageRef.current = onMessage }, [onMessage])
  useEffect(() => { onConnectionChangeRef.current = onConnectionChange }, [onConnectionChange])

  const connect = useCallback(() => {
    if (!token) return

    // Build the WebSocket URL — use wss:// in production (HTTPS page)
    const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const url = `${protocol}://${window.location.host}/ws?token=${encodeURIComponent(token)}`

    const ws = new WebSocket(url)
    wsRef.current = ws

    ws.onopen = () => {
      onConnectionChangeRef.current?.(true)
    }

    ws.onmessage = (event: MessageEvent) => {
      try {
        const parsed = JSON.parse(event.data as string)
        onMessageRef.current(parsed)
      } catch {
        // Ignore malformed messages
      }
    }

    ws.onclose = () => {
      onConnectionChangeRef.current?.(false)
      wsRef.current = null
      // Schedule reconnection unless the hook is being cleaned up
      if (token) {
        reconnectTimerRef.current = setTimeout(connect, RECONNECT_DELAY_MS)
      }
    }

    ws.onerror = () => {
      // onclose fires after onerror, so reconnection is handled there
      ws.close()
    }
  }, [token])

  useEffect(() => {
    if (!token) {
      // Tear down any existing connection when the user logs out
      wsRef.current?.close()
      wsRef.current = null
      return
    }

    connect()

    return () => {
      // Clean up on unmount or token change
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current)
        reconnectTimerRef.current = null
      }
      wsRef.current?.close()
      wsRef.current = null
    }
  }, [token, connect])
}
