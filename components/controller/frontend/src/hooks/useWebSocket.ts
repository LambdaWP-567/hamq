import { useEffect, useRef, useCallback, useState } from 'react'
import type { ControllerStatus } from '../types'

const TOKEN_KEY = 'hamq_controller_token'

type WebSocketStatus = 'connecting' | 'connected' | 'disconnected' | 'error'

interface UseWebSocketOptions {
  enabled?: boolean
  onMessage?: (status: ControllerStatus) => void
  onError?: (error: Event) => void
}

interface UseWebSocketResult {
  status: WebSocketStatus
  lastMessage: ControllerStatus | null
  reconnect: () => void
}

const RECONNECT_DELAYS = [1_000, 2_000, 4_000, 8_000, 16_000] // exponential backoff
const MAX_RECONNECT_ATTEMPTS = 10

export function useWebSocket(options: UseWebSocketOptions = {}): UseWebSocketResult {
  const { enabled = true, onMessage, onError } = options

  const [wsStatus, setWsStatus] = useState<WebSocketStatus>('disconnected')
  const [lastMessage, setLastMessage] = useState<ControllerStatus | null>(null)

  const wsRef = useRef<WebSocket | null>(null)
  const reconnectAttemptsRef = useRef(0)
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const mountedRef = useRef(true)

  const connect = useCallback(() => {
    if (!mountedRef.current || !enabled) return

    const token = localStorage.getItem(TOKEN_KEY)
    if (!token) {
      setWsStatus('disconnected')
      return
    }

    // Determine the correct WebSocket URL based on the current page location
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const host = window.location.host
    const url = `${protocol}//${host}/ws?token=${encodeURIComponent(token)}`

    setWsStatus('connecting')

    const ws = new WebSocket(url)
    wsRef.current = ws

    ws.onopen = () => {
      if (!mountedRef.current) return
      setWsStatus('connected')
      reconnectAttemptsRef.current = 0
    }

    ws.onmessage = (event: MessageEvent<string>) => {
      if (!mountedRef.current) return
      try {
        const parsed = JSON.parse(event.data) as ControllerStatus
        setLastMessage(parsed)
        onMessage?.(parsed)
      } catch {
        // Ignore malformed messages
      }
    }

    ws.onerror = (event: Event) => {
      if (!mountedRef.current) return
      setWsStatus('error')
      onError?.(event)
    }

    ws.onclose = () => {
      if (!mountedRef.current) return
      setWsStatus('disconnected')
      wsRef.current = null

      // Attempt reconnect with exponential backoff
      if (reconnectAttemptsRef.current < MAX_RECONNECT_ATTEMPTS && enabled) {
        const attempt = Math.min(reconnectAttemptsRef.current, RECONNECT_DELAYS.length - 1)
        const delay = RECONNECT_DELAYS[attempt] ?? 16_000
        reconnectAttemptsRef.current += 1
        reconnectTimerRef.current = setTimeout(connect, delay)
      }
    }
  }, [enabled, onMessage, onError])

  const reconnect = useCallback(() => {
    // Cancel any pending reconnect timer
    if (reconnectTimerRef.current !== null) {
      clearTimeout(reconnectTimerRef.current)
      reconnectTimerRef.current = null
    }
    // Close existing connection
    if (wsRef.current) {
      wsRef.current.onclose = null // prevent automatic reconnect loop
      wsRef.current.close()
      wsRef.current = null
    }
    reconnectAttemptsRef.current = 0
    connect()
  }, [connect])

  useEffect(() => {
    mountedRef.current = true

    if (enabled) {
      connect()
    }

    return () => {
      mountedRef.current = false

      if (reconnectTimerRef.current !== null) {
        clearTimeout(reconnectTimerRef.current)
      }

      if (wsRef.current) {
        wsRef.current.onclose = null
        wsRef.current.close()
        wsRef.current = null
      }
    }
  }, [enabled, connect])

  return { status: wsStatus, lastMessage, reconnect }
}
