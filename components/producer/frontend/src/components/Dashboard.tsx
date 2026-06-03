/**
 * Dashboard.tsx — Main dashboard for the HAMq Producer UI.
 *
 * Shows the producer's live status, control panel, message log, and
 * real-time statistics charts.  All data flows through a single WebSocket
 * connection whose updates are fanned out to child components via props.
 */

import React, { useState, useCallback, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import type { AxiosInstance } from 'axios'

import { useWebSocket } from '../hooks/useWebSocket'
import type { ProducerStatus, Message, RateDataPoint } from '../types'
import StatusCard from './StatusCard'
import ProducerControl from './ProducerControl'
import MessageLog from './MessageLog'
import Stats from './Stats'
import LanguageSwitcher from './LanguageSwitcher'

// Maximum data points kept in the rate chart history
const MAX_RATE_POINTS = 60

interface DashboardProps {
  token: string | null
  api: AxiosInstance
  onLogout: () => void
}

export default function Dashboard({ token, api, onLogout }: DashboardProps) {
  const { t } = useTranslation()

  // Live producer status received from WebSocket
  const [status, setStatus] = useState<ProducerStatus | null>(null)
  // Rolling window of recent messages
  const [messages, setMessages] = useState<Message[]>([])
  // Time-series data for the rate chart
  const [rateHistory, setRateHistory] = useState<RateDataPoint[]>([])
  // Whether the WebSocket connection is alive
  const [wsConnected, setWsConnected] = useState(false)

  // ------------------------------------------------------------------
  // WebSocket handler
  // ------------------------------------------------------------------
  const handleWsMessage = useCallback((data: unknown) => {
    const payload = data as {
      type?: string
      status?: ProducerStatus
      recent_messages?: Message[]
    }

    if (payload.status) {
      const s = payload.status
      setStatus(s)

      // Append a new rate data point
      setRateHistory((prev) => {
        const point: RateDataPoint = {
          time: Date.now(),
          sent: s.sent_count,
          buffered: s.buffered_count,
        }
        const next = [...prev, point]
        return next.length > MAX_RATE_POINTS
          ? next.slice(next.length - MAX_RATE_POINTS)
          : next
      })
    }

    if (payload.recent_messages) {
      setMessages(payload.recent_messages.slice(-100))
    }
  }, [])

  const handleConnectionChange = useCallback((connected: boolean) => {
    setWsConnected(connected)
  }, [])

  useWebSocket({
    token,
    onMessage: handleWsMessage,
    onConnectionChange: handleConnectionChange,
  })

  // ------------------------------------------------------------------
  // Fetch initial status on mount
  // ------------------------------------------------------------------
  useEffect(() => {
    let cancelled = false
    api
      .get<ProducerStatus>('/api/v1/producer/status')
      .then((res) => {
        if (!cancelled) setStatus(res.data)
      })
      .catch(() => {
        // Status will arrive via WebSocket once connected
      })
    return () => {
      cancelled = true
    }
  }, [api])

  // ------------------------------------------------------------------
  // Derived status values
  // ------------------------------------------------------------------
  const kafkaVariant = status?.kafka_connected ? 'success' : 'danger'
  const runningVariant = status?.running ? 'success' : 'warning'

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900">
      {/* ----------------------------------------------------------------
          Navigation bar
      ---------------------------------------------------------------- */}
      <nav className="bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 shadow-sm">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex items-center justify-between h-16">
            {/* Left: title + producer ID */}
            <div className="flex items-center gap-3">
              <h1 className="text-lg font-bold text-gray-900 dark:text-white">
                {t('nav.title')}
              </h1>
              {status && (
                <span className="hidden sm:inline text-sm text-gray-500 dark:text-gray-400 font-mono">
                  {status.producer_id}
                </span>
              )}
            </div>

            {/* Right: WS indicator, language switcher, logout */}
            <div className="flex items-center gap-3">
              {/* WebSocket connection indicator */}
              <div className="flex items-center gap-1.5">
                <span
                  className={`inline-block h-2 w-2 rounded-full ${
                    wsConnected ? 'bg-green-500' : 'bg-red-400'
                  }`}
                  title={wsConnected ? 'WebSocket connected' : 'WebSocket disconnected'}
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

      {/* ----------------------------------------------------------------
          Main content
      ---------------------------------------------------------------- */}
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6 space-y-6">
        {/* Status cards row */}
        <section aria-label="Status overview">
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-4">
            <StatusCard
              label={t('status.running')}
              value={status?.running ? t('status.running') : t('status.stopped')}
              variant={runningVariant}
              icon={
                <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                    d={status?.running
                      ? 'M10 9v6m4-6v6m7-3a9 9 0 11-18 0 9 9 0 0118 0z'
                      : 'M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z'
                    }
                  />
                </svg>
              }
            />
            <StatusCard
              label="Kafka"
              value={status?.kafka_connected ? t('status.connected') : t('status.disconnected')}
              variant={kafkaVariant}
              icon={
                <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                    d="M13 10V3L4 14h7v7l9-11h-7z" />
                </svg>
              }
            />
            <StatusCard
              label={t('status.sent')}
              value={status?.sent_count ?? 0}
              variant="info"
              icon={
                <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                    d="M9 5l7 7-7 7" />
                </svg>
              }
            />
            <StatusCard
              label={t('status.buffered')}
              value={status?.buffered_count ?? 0}
              variant={
                (status?.buffered_count ?? 0) > 1000 ? 'warning' : 'default'
              }
              icon={
                <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                    d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4" />
                </svg>
              }
            />
            <StatusCard
              label={t('status.errors')}
              value={status?.error_count ?? 0}
              variant={(status?.error_count ?? 0) > 0 ? 'danger' : 'default'}
              icon={
                <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                    d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                </svg>
              }
            />
          </div>
        </section>

        {/* Control panel + Stats side-by-side on wider screens */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <ProducerControl
            status={status}
            token={token}
            api={api}
            onStatusChange={setStatus}
          />
          <Stats rateHistory={rateHistory} status={status} />
        </div>

        {/* Message log — full width */}
        <MessageLog messages={messages} />
      </main>
    </div>
  )
}
