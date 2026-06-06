import React, { useState, useEffect, useCallback, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { Zap, Play, Square, AlertTriangle, Info } from 'lucide-react'
import clsx from 'clsx'
import { useApi } from '../hooks/useApi'
import { useWebSocket } from '../hooks/useWebSocket'
import LanguageSwitcher from './LanguageSwitcher'
import CounterCharts from './CounterCharts'

interface HistoryPoint {
  time: string
  sent: number
  received: number | null
  send_rate: number
  recv_rate: number
  missing_count: number
}

interface OrchestratorStatus {
  running: boolean
  cycle: number
  sent_counter: number
  total_sent: number
  send_rate: number
  recv_counter: number | null
  total_received: number
  recv_rate: number
  counter_max: number
  freq_hz: number
  missing_count: number
  completion_pct: number
  missing_sample: { number: number; first_seen: string }[]
  history: HistoryPoint[]
}

interface Props {
  token: string
  onLogout: () => void
}

export default function Dashboard({ token, onLogout }: Props) {
  const { t } = useTranslation()
  const api = useApi(token)

  const [status, setStatus] = useState<OrchestratorStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [actionPending, setActionPending] = useState(false)
  const [freqHz, setFreqHz] = useState(10)
  const [counterMax, setCounterMax] = useState(10000)
  const freqDebounce = useRef<ReturnType<typeof setTimeout> | null>(null)

  const handleFreqChange = (val: number) => {
    setFreqHz(val)
    if (freqDebounce.current) clearTimeout(freqDebounce.current)
    freqDebounce.current = setTimeout(() => {
      void api.updateConfig(val, undefined)
    }, 300)
  }

  const fetchStatus = useCallback(async () => {
    try {
      const data = await api.getStatus()
      setStatus(data)
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Error')
    } finally {
      setLoading(false)
    }
  }, [api])

  useEffect(() => {
    fetchStatus()
    const id = setInterval(fetchStatus, 3000)
    return () => clearInterval(id)
  }, [fetchStatus])

  useWebSocket(token, (data) => setStatus(data as OrchestratorStatus))

  const handleStart = async () => {
    setActionPending(true)
    try {
      await api.updateConfig(freqHz, counterMax)
      await api.startTest()
      await fetchStatus()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Error')
    } finally {
      setActionPending(false)
    }
  }

  const handleStop = async () => {
    setActionPending(true)
    try {
      await api.stopTest()
      await fetchStatus()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Error')
    } finally {
      setActionPending(false)
    }
  }

  const running = status?.running ?? false

  const cards = [
    { label: t('cards.sent'),       value: status?.total_sent.toLocaleString()     ?? '—', color: 'blue'   },
    { label: t('cards.received'),   value: status?.total_received.toLocaleString() ?? '—', color: 'green'  },
    { label: t('cards.missing'),    value: status?.missing_count.toLocaleString()  ?? '—', color: status?.missing_count ? 'red' : 'gray' },
    { label: t('cards.cycle'),      value: String(status?.cycle ?? 0),                      color: 'purple' },
    { label: t('cards.completion'), value: `${status?.completion_pct ?? 0}%`,               color: status?.completion_pct === 100 ? 'green' : 'orange' },
  ]

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900">
      {/* Header */}
      <header className="bg-white dark:bg-gray-800 shadow-sm border-b border-gray-200 dark:border-gray-700">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Zap className="w-7 h-7 text-violet-500" />
            <div>
              <h1 className="text-xl font-bold text-gray-900 dark:text-white leading-tight">
                {t('header.title')}
              </h1>
              <p className="text-xs text-gray-500 dark:text-gray-400">
                {t('header.subtitle')}
                <span className="ml-2 inline-flex items-center text-xs font-mono font-medium bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300 px-1.5 py-0.5 rounded">
                  v{import.meta.env.VITE_APP_VERSION ?? 'dev'}
                </span>
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <span className={clsx(
              'flex items-center gap-1.5 text-sm font-medium px-3 py-1 rounded-full',
              running
                ? 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400'
                : 'bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-400'
            )}>
              {running ? t('status.running') : t('status.stopped')}
            </span>
            <LanguageSwitcher />
            <button
              onClick={onLogout}
              className="text-sm font-medium text-gray-500 dark:text-gray-400
                         hover:text-gray-700 dark:hover:text-gray-200
                         px-3 py-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-700
                         transition-colors"
            >
              {t('auth.logout')}
            </button>
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6 space-y-6">
        {/* Control bar */}
        <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-4 flex flex-wrap items-center gap-4">
          <button
            onClick={handleStart}
            disabled={running || actionPending}
            className="flex items-center gap-2 px-4 py-2 rounded-lg bg-violet-600 hover:bg-violet-700 text-white text-sm font-semibold transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <Play className="w-4 h-4" />
            {actionPending && !running ? t('controls.starting') : t('controls.start')}
          </button>
          <button
            onClick={handleStop}
            disabled={!running || actionPending}
            className="flex items-center gap-2 px-4 py-2 rounded-lg bg-red-600 hover:bg-red-700 text-white text-sm font-semibold transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <Square className="w-4 h-4" />
            {actionPending && running ? t('controls.stopping') : t('controls.stop')}
          </button>

          <div className="flex items-center gap-2 ml-2">
            <label className="text-sm text-gray-600 dark:text-gray-400">{t('controls.freq')}:</label>
            <span className="relative group cursor-default">
              <Info className="w-3.5 h-3.5 text-gray-400 hover:text-gray-600 dark:hover:text-gray-200" />
              <span className="pointer-events-none absolute bottom-full left-1/2 -translate-x-1/2 mb-2 w-56 rounded-lg bg-gray-900 text-white text-xs px-3 py-2 opacity-0 group-hover:opacity-100 transition-opacity z-50 shadow-lg">
                Anzahl Nachrichten, die der Producer pro Sekunde an Kafka sendet. Kann live während des Tests geändert werden.
              </span>
            </span>
            <input
              type="range"
              min={1}
              max={100}
              value={freqHz}
              onChange={e => handleFreqChange(Number(e.target.value))}
              className="w-28 accent-violet-600"
            />
            <span className="text-sm font-mono text-gray-700 dark:text-gray-300 w-16">
              {freqHz} {t('controls.hz')}
            </span>
          </div>

          <div className="flex items-center gap-2">
            <label className="text-sm text-gray-600 dark:text-gray-400">{t('controls.maxCounter')}:</label>
            <select
              value={counterMax}
              onChange={e => setCounterMax(Number(e.target.value))}
              disabled={running}
              className="text-sm rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white px-2 py-1"
            >
              {[100, 1000, 10000, 100000].map(v => (
                <option key={v} value={v}>{v.toLocaleString()}</option>
              ))}
            </select>
          </div>
        </div>

        {error && (
          <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-xl p-4 flex gap-2 text-red-700 dark:text-red-400 text-sm">
            <AlertTriangle className="w-4 h-4 flex-shrink-0 mt-0.5" />
            {error}
          </div>
        )}

        {/* Summary cards */}
        <div className="grid grid-cols-2 sm:grid-cols-5 gap-4">
          {cards.map(({ label, value, color }) => (
            <div key={label} className="bg-white dark:bg-gray-800 rounded-xl p-4 shadow-sm border border-gray-200 dark:border-gray-700">
              <p className="text-xs text-gray-500 dark:text-gray-400 mb-1">{label}</p>
              <p className={clsx('text-2xl font-bold tabular-nums', {
                'text-blue-600 dark:text-blue-400':   color === 'blue',
                'text-green-600 dark:text-green-400': color === 'green',
                'text-red-600 dark:text-red-400':     color === 'red',
                'text-purple-600 dark:text-purple-400': color === 'purple',
                'text-orange-500 dark:text-orange-400': color === 'orange',
                'text-gray-600 dark:text-gray-400':   color === 'gray',
              })}>
                {loading ? '…' : value}
              </p>
            </div>
          ))}
        </div>

        {/* Counter value current state */}
        {status && (
          <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-4">
            <div className="flex items-center gap-8">
              <div>
                <p className="text-xs text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-0.5">Producer → {status.counter_max.toLocaleString()}</p>
                <p className="text-3xl font-bold tabular-nums text-blue-600 dark:text-blue-400">
                  {status.sent_counter.toLocaleString()}
                </p>
                <p className="text-xs text-gray-400 mt-0.5">{status.send_rate.toFixed(1)} msg/s</p>
              </div>
              <div className="text-gray-300 dark:text-gray-600 text-2xl">→</div>
              <div>
                <p className="text-xs text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-0.5">Consumer</p>
                <p className="text-3xl font-bold tabular-nums text-green-600 dark:text-green-400">
                  {status.recv_counter?.toLocaleString() ?? '—'}
                </p>
                <p className="text-xs text-gray-400 mt-0.5">{status.recv_rate.toFixed(1)} msg/s</p>
              </div>
            </div>
          </div>
        )}

        {/* Charts + judge */}
        <CounterCharts
          history={status?.history ?? []}
          missingSample={status?.missing_sample ?? []}
          missingCount={status?.missing_count ?? 0}
          counterMax={status?.counter_max ?? 10000}
          freqHz={status?.freq_hz ?? freqHz}
        />
      </main>
    </div>
  )
}
