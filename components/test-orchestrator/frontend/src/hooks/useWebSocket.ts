import { useEffect, useRef, useCallback } from 'react'

export function useWebSocket(token: string | null, onMessage: (data: unknown) => void) {
  const wsRef = useRef<WebSocket | null>(null)
  const retryDelay = useRef(1000)
  const mountedRef = useRef(true)

  const connect = useCallback(() => {
    if (!token || !mountedRef.current) return
    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const url = `${proto}://${window.location.host}/ws?token=${token}`
    const ws = new WebSocket(url)
    wsRef.current = ws

    ws.onmessage = (ev) => {
      try {
        onMessage(JSON.parse(ev.data))
        retryDelay.current = 1000
      } catch (_) {}
    }

    ws.onclose = () => {
      if (!mountedRef.current) return
      setTimeout(() => {
        retryDelay.current = Math.min(retryDelay.current * 2, 16000)
        connect()
      }, retryDelay.current)
    }

    ws.onerror = () => ws.close()
  }, [token, onMessage])

  useEffect(() => {
    mountedRef.current = true
    connect()
    return () => {
      mountedRef.current = false
      wsRef.current?.close()
    }
  }, [connect])
}
