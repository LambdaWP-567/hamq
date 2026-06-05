import React, { useState, useCallback, useEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'

import { useApi } from '../hooks/useApi'
import { useWebSocket } from '../hooks/useWebSocket'
import type {
  ConsumerStatus,
  ReceivedMessage,
  ReceiveRatePoint,
  StatusUpdate,
} from '../types'
import MessageLog from './MessageLog'
import Stats from './Stats'
import LanguageSwitcher from './LanguageSwitcher'
import InfoTooltip from './InfoTooltip'

const MAX_RATE_POINTS = 60

interface DashboardProps {
  token: string | null
  onLogout: () => void
}

export default function Dashboard({ token, onLogout }: DashboardProps) {
  const { t } = useTranslation()
  const api = useApi()

  const [status, setStatus] = useState<ConsumerStatus | null>(null)
  const [messages, setMessages] = useState<ReceivedMessage[]>([])
  const [rateHistory, setRateHistory] = useState<ReceiveRatePoint[]>([])
  const [wsConnected, setWsConnected] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const [actionPending, setActionPending] = useState(false)

  // ------------------------------------------------------------------
  // WebSocket: handle real-time status updates
  // ------------------------------------------------------------------
  const handleWsMessage = useCallback((update: StatusUpdate) => {
    const s = update.status
    setStatus(s)

    const label = new Date().toLocaleTimeString('en-GB', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    })
    setRateHistory((prev) => {
      const lastReceived = prev.length > 0 ? prev[prev.length - 1].received : s.received_count
      const rate = Math.max(0, s.received_count - lastReceived)
      const point: ReceiveRatePoint = { time: label, rate, received: s.received_count }
      const next = [...prev, point]
      return next.length > MAX_RATE_POINTS
        ? next.slice(next.length - MAX_RATE_POINTS)
        : next
    })

    if (update.recent_messages) {
      setMessages(update.recent_messages.slice(-50))
    }
  }, [])

  const { connected } = useWebSocket({ token, onMessage: handleWsMessage })

  useEffect(() => {
    setWsConnected(connected)
  }, [connected])

  // ------------------------------------------------------------------
  // Auto-start consuming on mount (once), then poll status every 2 s
  // ------------------------------------------------------------------
  const autoStarted = useRef(false)

  useEffect(() => {
    let cancelled = false

    const fetchStatus = () => {
      api.getStatus()
        .then((s) => { if (!cancelled) setStatus(s) })
        .catch(() => {})
    }

    // Auto-start on first load if the consumer is not already running
    if (!autoStarted.current) {
      autoStarted.current = true
      ;(async () => {
        try {
          const s = await api.getStatus()
          if (!cancelled) setStatus(s)
          if (!s.running) {
            await api.startConsumer()
            const updated = await api.getStatus()
            if (!cancelled) setStatus(updated)
          }
        } catch {}
      })()
    } else {
      fetchStatus()
    }

    const id = setInterval(fetchStatus, 2000)
    return () => { cancelled = true; clearInterval(id) }
  }, [api])

  // ------------------------------------------------------------------
  // Start / Stop consumer (manual toggle)
  // ------------------------------------------------------------------
  const handleToggle = useCallback(async () => {
    if (!status) return
    setActionError(null)
    setActionPending(true)
    try {
      if (status.running) {
        await api.stopConsumer()
      } else {
        await api.startConsumer()
      }
      const updated = await api.getStatus()
      setStatus(updated)
    } catch {
      setActionError(status.running ? t('controls.stop') : t('controls.start'))
    } finally {
      setActionPending(false)
    }
  }, [api, status, t])

  const isRunning = status?.running ?? false
  const lagVariant = (status?.lag_estimate ?? 0) > 1000 ? 'warning' : 'ok'

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900">
      {/* Navigation bar */}
      <nav className="bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 shadow-sm">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex items-center justify-between h-16">
            <div className="flex items-center gap-3">
              <h1 className="text-lg font-bold text-gray-900 dark:text-white">
                {t('nav.title')}
              </h1>
              {status && (
                <span className="hidden sm:inline text-sm text-gray-500 dark:text-gray-400 font-mono">
                  {status.consumer_id}
                </span>
              )}
            </div>

            <div className="flex items-center gap-3">
              <div className="flex items-center gap-1.5">
                <span
                  className={`inline-block h-2 w-2 rounded-full ${
                    wsConnected ? 'bg-green-500' : 'bg-red-400'
                  }`}
                />
                <span className="hidden sm:inline text-xs text-gray-500 dark:text-gray-400">
                  {wsConnected ? 'Live' : 'Offline'}
                </span>
              </div>

              <LanguageSwitcher />

              <button
                onClick={onLogout}
                className="text-sm font-medium text-gray-500 dark:text-gray-400
                           hover:text-gray-700 dark:hover:text-gray-200
                           px-3 py-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-700
                           transition-colors duration-150"
              >
                {t('nav.logout')}
              </button>
            </div>
          </div>
        </div>
      </nav>

      {/* Main content */}
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6 space-y-6">

        {/* Status cards */}
        <section className="grid grid-cols-2 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {/* Kafka connection */}
          <div className={`bg-white dark:bg-gray-800 rounded-xl border shadow-sm p-4 border-l-4
            ${status?.kafka_connected
              ? 'border-green-200 dark:border-green-700'
              : 'border-red-200 dark:border-red-700'}`}>
            <p className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide">
              Kafka
            </p>
            <p className={`mt-1 text-xl font-bold ${
              status?.kafka_connected
                ? 'text-green-700 dark:text-green-400'
                : 'text-red-700 dark:text-red-400'
            }`}>
              {status?.kafka_connected
                ? t('status.kafka_connected')
                : t('status.kafka_disconnected')}
            </p>
          </div>

          {/* Messages received */}
          <div className="bg-white dark:bg-gray-800 rounded-xl border border-blue-200 dark:border-blue-700 border-l-4 shadow-sm p-4">
            <p className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide">
              {t('status.received')}
            </p>
            <p className="mt-1 text-2xl font-bold text-blue-700 dark:text-blue-400 tabular-nums">
              {(status?.received_count ?? 0).toLocaleString()}
            </p>
          </div>

          {/* Consumer lag — with unit + tooltip */}
          <div className={`bg-white dark:bg-gray-800 rounded-xl border shadow-sm p-4 border-l-4
            ${lagVariant === 'warning'
              ? 'border-yellow-200 dark:border-yellow-700'
              : 'border-gray-200 dark:border-gray-600'}`}>
            <p className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide flex items-center">
              {t('status.lag')}
              <InfoTooltip text={t('tooltips.lag')} />
            </p>
            <p className={`mt-1 text-2xl font-bold tabular-nums ${
              lagVariant === 'warning'
                ? 'text-yellow-700 dark:text-yellow-400'
                : 'text-gray-800 dark:text-gray-200'
            }`}>
              {(status?.lag_estimate ?? 0).toLocaleString()}
              <span className="ml-1 text-xs font-normal text-gray-500 dark:text-gray-400">
                {t('tooltips.lag_unit')}
              </span>
            </p>
          </div>

          {/* Checksum errors — with tooltip */}
          <div className={`bg-white dark:bg-gray-800 rounded-xl border shadow-sm p-4 border-l-4
            ${(status?.checksum_errors ?? 0) > 0
              ? 'border-red-200 dark:border-red-700'
              : 'border-gray-200 dark:border-gray-600'}`}>
            <p className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide flex items-center">
              {t('status.checksum_errors')}
              <InfoTooltip text={t('tooltips.checksum')} />
            </p>
            <p className={`mt-1 text-2xl font-bold tabular-nums ${
              (status?.checksum_errors ?? 0) > 0
                ? 'text-red-700 dark:text-red-400'
                : 'text-gray-800 dark:text-gray-200'
            }`}>
              {(status?.checksum_errors ?? 0).toLocaleString()}
            </p>
          </div>
        </section>

        {/* Control panel */}
        <section className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 shadow-sm p-5 space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-base font-semibold text-gray-900 dark:text-white">
              {t('controls.title')}
            </h2>
            <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium
              ${isRunning
                ? 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400'
                : 'bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300'}`}>
              <span className={`h-1.5 w-1.5 rounded-full ${isRunning ? 'bg-green-500' : 'bg-gray-400'}`} />
              {isRunning ? t('status.running') : t('status.stopped')}
            </span>
          </div>

          {status?.consumer_id && (
            <div>
              <p className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-1">
                {t('status.consumer_id')}
              </p>
              <p className="text-sm font-mono bg-gray-50 dark:bg-gray-700 rounded-lg px-3 py-2 text-gray-800 dark:text-gray-200 select-all">
                {status.consumer_id}
              </p>
            </div>
          )}

          <button
            onClick={handleToggle}
            disabled={actionPending || !status}
            className={`w-full sm:w-auto flex items-center justify-center gap-2 px-5 py-2.5 rounded-lg
              text-sm font-semibold transition-colors duration-150
              disabled:opacity-60 disabled:cursor-not-allowed
              ${isRunning
                ? 'bg-red-500 hover:bg-red-600 text-white'
                : 'bg-blue-600 hover:bg-blue-700 text-white'}`}
          >
            {actionPending ? (
              <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" />
            ) : (
              <svg className="h-4 w-4" fill="currentColor" viewBox="0 0 24 24">
                {isRunning
                  ? <path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z" />
                  : <path d="M8 5v14l11-7z" />}
              </svg>
            )}
            {isRunning ? t('controls.stop') : t('controls.start')}
          </button>

          {actionError && (
            <div className="rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800
                            px-4 py-3 text-sm text-red-700 dark:text-red-400 flex items-start gap-2">
              <span>{actionError}</span>
              <button onClick={() => setActionError(null)} className="ml-auto text-red-400 hover:text-red-600">×</button>
            </div>
          )}
        </section>

        {/* Stats + MessageLog */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <Stats rateHistory={rateHistory} status={status} />
          <MessageLog messages={messages} />
        </div>
      </main>
    </div>
  )
}
