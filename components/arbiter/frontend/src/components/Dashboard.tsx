/**
 * Dashboard — Main arbiter view.
 *
 * Polls GET /api/status every 5 s and subscribes to the WebSocket for
 * real-time reconcile reports.  Renders summary cards, ReconcileControl,
 * GapReport (audit table), and Stats charts.
 */

import React, { useState, useEffect, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { useApi } from '../hooks/useApi'
import { useWebSocket } from '../hooks/useWebSocket'
import ReconcileControl from './ReconcileControl'
import GapReport from './GapReport'
import Stats from './Stats'
import type {
  ArbiterStatus,
  ReconcileReport,
  AuditStats,
  WsMessage,
} from '../types'

interface DashboardProps {
  token: string | null
  onLogout: () => void
}

// ---------------------------------------------------------------------------
// Small summary card component (local, not exported)
// ---------------------------------------------------------------------------

interface SummaryCardProps {
  label: string
  value: string | number
  subtext?: string
  variant?: 'default' | 'success' | 'warning' | 'danger'
}

function SummaryCard({ label, value, subtext, variant = 'default' }: SummaryCardProps) {
  const borderColor = {
    default:  'border-l-gray-300',
    success:  'border-l-green-400',
    warning:  'border-l-yellow-400',
    danger:   'border-l-red-500',
  }[variant]

  const valueColor = {
    default:  'text-gray-900',
    success:  'text-green-700',
    warning:  'text-yellow-700',
    danger:   'text-red-700',
  }[variant]

  return (
    <div className={`card border-l-4 ${borderColor}`}>
      <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide truncate">{label}</p>
      <p className={`mt-1 text-2xl font-bold tabular-nums ${valueColor}`}>
        {typeof value === 'number' ? value.toLocaleString() : value}
      </p>
      {subtext && <p className="mt-1 text-xs text-gray-400 truncate">{subtext}</p>}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Dashboard
// ---------------------------------------------------------------------------

export default function Dashboard({ token, onLogout }: DashboardProps) {
  const { t, i18n } = useTranslation()
  const api = useApi(token)

  const [status, setStatus] = useState<ArbiterStatus | null>(null)
  const [latestReport, setLatestReport] = useState<ReconcileReport | null>(null)
  const [stats, setStats] = useState<AuditStats | null>(null)
  const [wsConnected, setWsConnected] = useState(false)
  const [activeTab, setActiveTab] = useState<'gaps' | 'stats'>('gaps')

  const currentLang = i18n.language.startsWith('de') ? 'de' : 'en'

  const toggleLanguage = () => {
    const next = currentLang === 'en' ? 'de' : 'en'
    i18n.changeLanguage(next)
    localStorage.setItem('hamq-arbiter-lang', next)
  }

  // ---------------------------------------------------------------------------
  // Fetch arbiter status and stats
  // ---------------------------------------------------------------------------

  const fetchStatus = useCallback(async () => {
    try {
      const res = await api.get<ArbiterStatus>('/api/status')
      setStatus(res.data)
    } catch {
      // Ignore — display last known state
    }
  }, [api])

  const fetchStats = useCallback(async () => {
    try {
      const res = await api.get<AuditStats>('/api/stats')
      setStats(res.data)
    } catch {
      // Ignore
    }
  }, [api])

  // Poll status every 5 seconds
  useEffect(() => {
    fetchStatus()
    fetchStats()
    const interval = setInterval(() => {
      fetchStatus()
      fetchStats()
    }, 5000)
    return () => clearInterval(interval)
  }, [fetchStatus, fetchStats])

  // ---------------------------------------------------------------------------
  // WebSocket handler
  // ---------------------------------------------------------------------------

  const handleWsMessage = useCallback((msg: WsMessage) => {
    if (msg.type === 'status') {
      setStatus(msg.data)
    } else if (msg.type === 'report') {
      setLatestReport(msg.data)
    }
  }, [])

  useWebSocket({
    token,
    onMessage: handleWsMessage,
    onConnectionChange: setWsConnected,
  })

  // ---------------------------------------------------------------------------
  // Derived values for summary cards
  // ---------------------------------------------------------------------------

  const totalSent = latestReport?.total_sent ?? 0
  const totalReceived = latestReport?.total_received ?? 0
  const totalMissing = latestReport?.total_missing ?? 0
  const successRate =
    totalSent > 0
      ? ((totalSent - totalMissing) / totalSent * 100).toFixed(1)
      : '—'

  const lastReconcileLabel = status?.last_reconcile_at
    ? new Date(status.last_reconcile_at).toLocaleTimeString()
    : t('status.never')

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div className="min-h-screen bg-gray-50 flex flex-col">
      {/* ------------------------------------------------------------------ */}
      {/* Header */}
      {/* ------------------------------------------------------------------ */}
      <header className="bg-gradient-to-r from-brand-700 to-brand-900 shadow-md">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            {/* Icon */}
            <div className="w-9 h-9 rounded-lg bg-white/20 flex items-center justify-center flex-shrink-0">
              <svg className="w-5 h-5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round"
                  d="M9 12.75L11.25 15 15 9.75m-3-7.036A11.959 11.959 0 013.598 6 11.99 11.99 0 003 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285z" />
              </svg>
            </div>
            <div>
              <h1 className="text-xl font-bold text-white leading-none">{t('nav.title')}</h1>
              <p className="text-brand-200 text-xs mt-0.5">{t('nav.dashboard')}</p>
            </div>
          </div>

          <div className="flex items-center gap-3">
            {/* WS connection indicator */}
            <div className="hidden sm:flex items-center gap-1.5 text-xs text-brand-200">
              <span className={`w-2 h-2 rounded-full ${wsConnected ? 'bg-green-400' : 'bg-red-400'}`} />
              <span>{wsConnected ? 'Live' : t('errors.connection_lost')}</span>
            </div>

            {/* Reconcile status badge */}
            {status && (
              <span className={`hidden sm:inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium
                ${status.running
                  ? 'bg-green-100 text-green-800'
                  : 'bg-gray-100 text-gray-700'
                }`}>
                {status.running ? t('status.running') : t('status.stopped')}
              </span>
            )}

            {/* Language toggle */}
            <button
              onClick={toggleLanguage}
              className="px-2.5 py-1.5 rounded-lg text-xs font-medium bg-white/10 hover:bg-white/20 text-white border border-white/20 transition-colors"
            >
              {currentLang.toUpperCase()}
            </button>

            {/* Logout */}
            <button
              onClick={onLogout}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium
                         bg-white/10 hover:bg-white/20 text-white border border-white/20
                         transition-colors duration-150"
              title="Logout"
            >
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round"
                  d="M15.75 9V5.25A2.25 2.25 0 0013.5 3h-6a2.25 2.25 0 00-2.25 2.25v13.5A2.25 2.25 0 007.5 21h6a2.25 2.25 0 002.25-2.25V15M12 9l-3 3m0 0l3 3m-3-3h12.75" />
              </svg>
              <span className="hidden sm:inline">Logout</span>
            </button>
          </div>
        </div>
      </header>

      {/* ------------------------------------------------------------------ */}
      {/* Main content */}
      {/* ------------------------------------------------------------------ */}
      <main className="flex-1 max-w-7xl mx-auto w-full px-4 sm:px-6 lg:px-8 py-6 space-y-6">

        {/* Summary cards */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          <SummaryCard
            label={t('report.total_sent')}
            value={totalSent}
            subtext={`${t('status.last_reconcile')}: ${lastReconcileLabel}`}
            variant="default"
          />
          <SummaryCard
            label={t('report.total_received')}
            value={totalReceived}
            variant={totalReceived >= totalSent ? 'success' : 'warning'}
          />
          <SummaryCard
            label={t('report.total_missing')}
            value={totalMissing}
            subtext={status ? `${status.producers_monitored} ${t('status.producers_monitored')}` : undefined}
            variant={totalMissing === 0 ? 'success' : totalMissing < 10 ? 'warning' : 'danger'}
          />
          <SummaryCard
            label="Success Rate"
            value={successRate === '—' ? '—' : `${successRate}%`}
            subtext={`${t('status.total_audits')}: ${status?.total_audits ?? 0}`}
            variant={
              successRate === '—' ? 'default'
              : parseFloat(successRate as string) >= 99.9 ? 'success'
              : parseFloat(successRate as string) >= 95 ? 'warning'
              : 'danger'
            }
          />
        </div>

        {/* Two-column layout: ReconcileControl + latest report summary */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-1">
            <ReconcileControl
              token={token}
              status={status}
              onStatusChange={setStatus}
              onReportReceived={setLatestReport}
            />
          </div>
          <div className="lg:col-span-2">
            {latestReport && (
              <div className="card h-full">
                <h3 className="text-sm font-semibold text-gray-700 mb-3">{t('report.title')}</h3>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr>
                        <th className="table-header rounded-tl-lg">{t('audit.producer')}</th>
                        <th className="table-header">{t('audit.sent')}</th>
                        <th className="table-header">{t('audit.received')}</th>
                        <th className="table-header">{t('audit.missing')}</th>
                        <th className="table-header rounded-tr-lg">{t('audit.loss_rate')}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {latestReport.producers.map((p) => (
                        <tr key={p.audit_id} className="hover:bg-gray-50 transition-colors">
                          <td className="table-cell font-mono text-xs">{p.producer_id}</td>
                          <td className="table-cell tabular-nums">{p.sent_count.toLocaleString()}</td>
                          <td className="table-cell tabular-nums">{p.received_count.toLocaleString()}</td>
                          <td className={`table-cell tabular-nums font-medium ${p.missing_count > 0 ? 'text-red-600' : 'text-green-600'}`}>
                            {p.missing_count.toLocaleString()}
                          </td>
                          <td className={`table-cell tabular-nums font-semibold ${
                            p.loss_rate === 0 ? 'text-green-600'
                            : p.loss_rate < 5 ? 'text-yellow-600'
                            : 'text-red-600'
                          }`}>
                            {(p.loss_rate * 100).toFixed(2)}%
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <p className="mt-3 text-xs text-gray-400">
                  {t('report.duration')}: {latestReport.duration_ms}{t('report.ms')}
                </p>
              </div>
            )}
            {!latestReport && (
              <div className="card flex items-center justify-center h-40 text-gray-400 text-sm">
                {t('report.no_report')}
              </div>
            )}
          </div>
        </div>

        {/* Tabs: Gap Report | Stats */}
        <div>
          <div className="flex gap-1 border-b border-gray-200 mb-4">
            <button
              onClick={() => setActiveTab('gaps')}
              className={`px-4 py-2 text-sm font-medium rounded-t-lg transition-colors ${
                activeTab === 'gaps'
                  ? 'bg-white border border-b-white border-gray-200 text-brand-700 -mb-px'
                  : 'text-gray-500 hover:text-gray-700'
              }`}
            >
              {t('audit.title')}
            </button>
            <button
              onClick={() => setActiveTab('stats')}
              className={`px-4 py-2 text-sm font-medium rounded-t-lg transition-colors ${
                activeTab === 'stats'
                  ? 'bg-white border border-b-white border-gray-200 text-brand-700 -mb-px'
                  : 'text-gray-500 hover:text-gray-700'
              }`}
            >
              {t('stats.title')}
            </button>
          </div>

          {activeTab === 'gaps' && <GapReport token={token} />}
          {activeTab === 'stats' && <Stats token={token} stats={stats} />}
        </div>
      </main>
    </div>
  )
}
