/**
 * Stats — Charts for the HAMq Arbiter.
 *
 * Shows:
 * 1. Messages sent vs received over time (LineChart)
 * 2. Loss rate over time (AreaChart with colour threshold)
 * 3. Success rate gauge (RadialBarChart)
 * 4. Aggregate stats cards
 */

import React, { useState, useEffect, useCallback, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import {
  LineChart,
  Line,
  AreaChart,
  Area,
  RadialBarChart,
  RadialBar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts'
import { useApi } from '../hooks/useApi'
import type { AuditSummary, AuditStats } from '../types'

interface StatsProps {
  token: string | null
  /** Pre-fetched stats from the parent Dashboard (may be null on first render) */
  stats: AuditStats | null
}

interface TimeSeriesPoint {
  timeLabel: string
  sent: number
  received: number
  lossRatePct: number
}

export default function Stats({ token, stats }: StatsProps) {
  const { t } = useTranslation()
  const api = useApi(token)

  const [audits, setAudits] = useState<AuditSummary[]>([])
  const [loading, setLoading] = useState(true)

  const fetchAudits = useCallback(async () => {
    try {
      const res = await api.get<AuditSummary[]>('/api/audits?limit=100')
      setAudits(res.data)
    } catch {
      // Keep last state on error
    } finally {
      setLoading(false)
    }
  }, [api])

  useEffect(() => {
    fetchAudits()
    const interval = setInterval(fetchAudits, 15000)
    return () => clearInterval(interval)
  }, [fetchAudits])

  // ---------------------------------------------------------------------------
  // Derive time-series data — aggregate by minute bucket
  // ---------------------------------------------------------------------------

  const timeSeriesData = useMemo<TimeSeriesPoint[]>(() => {
    if (audits.length === 0) return []

    // Sort oldest first
    const sorted = [...audits].sort(
      (a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime()
    )

    // Group by 1-minute bucket
    const buckets = new Map<string, { sent: number; received: number; count: number }>()
    for (const audit of sorted) {
      const d = new Date(audit.timestamp)
      const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
      const existing = buckets.get(key) ?? { sent: 0, received: 0, count: 0 }
      existing.sent += audit.sent_count
      existing.received += audit.received_count
      existing.count += 1
      buckets.set(key, existing)
    }

    return Array.from(buckets.entries()).map(([timeLabel, data]) => ({
      timeLabel,
      sent: data.sent,
      received: data.received,
      lossRatePct:
        data.sent > 0
          ? parseFloat(((data.sent - data.received) / data.sent * 100).toFixed(2))
          : 0,
    }))
  }, [audits])

  // ---------------------------------------------------------------------------
  // Gauge data for RadialBarChart
  // ---------------------------------------------------------------------------

  const successRatePct = useMemo(() => {
    if (!stats || stats.total_audits === 0) return 100
    return parseFloat(((1 - stats.avg_loss_rate) * 100).toFixed(1))
  }, [stats])

  const gaugeData = [
    { name: 'Success Rate', value: successRatePct, fill: successRatePct >= 99 ? '#16a34a' : successRatePct >= 95 ? '#ca8a04' : '#dc2626' },
  ]

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  if (loading) {
    return (
      <div className="card flex items-center justify-center h-40 text-gray-400 text-sm">
        <span className="inline-block h-5 w-5 animate-spin rounded-full border-2 border-brand-400 border-t-transparent mr-2" />
        {t('common.loading')}
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Aggregate stats cards */}
      {stats && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          <div className="card text-center">
            <p className="text-xs text-gray-500 uppercase tracking-wide">{t('stats.total_audits')}</p>
            <p className="mt-1 text-2xl font-bold text-gray-900 tabular-nums">
              {stats.total_audits.toLocaleString()}
            </p>
          </div>
          <div className="card text-center">
            <p className="text-xs text-gray-500 uppercase tracking-wide">{t('stats.avg_loss_rate')}</p>
            <p className={`mt-1 text-2xl font-bold tabular-nums ${
              stats.avg_loss_rate === 0 ? 'text-green-600'
              : stats.avg_loss_rate < 0.05 ? 'text-yellow-600'
              : 'text-red-600'
            }`}>
              {(stats.avg_loss_rate * 100).toFixed(2)}%
            </p>
          </div>
          <div className="card text-center">
            <p className="text-xs text-gray-500 uppercase tracking-wide">{t('stats.worst_producer')}</p>
            <p className="mt-1 text-sm font-bold text-gray-900 truncate font-mono">
              {stats.worst_producer ?? t('common.unknown')}
            </p>
          </div>
          <div className="card text-center">
            <p className="text-xs text-gray-500 uppercase tracking-wide">{t('stats.producers_tracked')}</p>
            <p className="mt-1 text-2xl font-bold text-gray-900 tabular-nums">
              {stats.producers_tracked}
            </p>
          </div>
        </div>
      )}

      {timeSeriesData.length === 0 ? (
        <div className="card flex items-center justify-center h-40 text-gray-400 text-sm">
          {t('chart.no_data')}
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Messages sent vs received */}
          <div className="card lg:col-span-2">
            <h3 className="text-sm font-semibold text-gray-700 mb-4">Messages Sent vs Received</h3>
            <ResponsiveContainer width="100%" height={220}>
              <LineChart data={timeSeriesData} margin={{ top: 5, right: 20, left: 0, bottom: 5 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                <XAxis
                  dataKey="timeLabel"
                  tick={{ fontSize: 10, fill: '#9ca3af' }}
                  tickFormatter={(v: string) => v.slice(11)}
                  interval="preserveStartEnd"
                />
                <YAxis tick={{ fontSize: 10, fill: '#9ca3af' }} />
                <Tooltip
                  contentStyle={{ fontSize: 12, borderRadius: 8 }}
                  formatter={(value: number, name: string) => [value.toLocaleString(), name]}
                />
                <Legend iconSize={10} wrapperStyle={{ fontSize: 12 }} />
                <Line
                  type="monotone"
                  dataKey="sent"
                  stroke="#3b82f6"
                  strokeWidth={2}
                  dot={false}
                  name="Sent"
                />
                <Line
                  type="monotone"
                  dataKey="received"
                  stroke="#10b981"
                  strokeWidth={2}
                  dot={false}
                  name="Received"
                />
              </LineChart>
            </ResponsiveContainer>
          </div>

          {/* Success Rate Gauge */}
          <div className="card flex flex-col items-center justify-center">
            <h3 className="text-sm font-semibold text-gray-700 mb-2">Success Rate</h3>
            <div className="relative">
              <ResponsiveContainer width={160} height={160}>
                <RadialBarChart
                  cx="50%"
                  cy="50%"
                  innerRadius={50}
                  outerRadius={75}
                  startAngle={90}
                  endAngle={-270}
                  data={gaugeData}
                >
                  <RadialBar
                    dataKey="value"
                    background={{ fill: '#f3f4f6' }}
                    cornerRadius={8}
                  />
                </RadialBarChart>
              </ResponsiveContainer>
              <div className="absolute inset-0 flex items-center justify-center flex-col">
                <span className={`text-2xl font-bold tabular-nums ${
                  successRatePct >= 99 ? 'text-green-600'
                  : successRatePct >= 95 ? 'text-yellow-600'
                  : 'text-red-600'
                }`}>
                  {successRatePct}%
                </span>
              </div>
            </div>
            <p className="text-xs text-gray-400 mt-1">avg across all audits</p>
          </div>

          {/* Loss rate over time */}
          <div className="card lg:col-span-3">
            <h3 className="text-sm font-semibold text-gray-700 mb-4">{t('chart.loss_rate_title')}</h3>
            <ResponsiveContainer width="100%" height={180}>
              <AreaChart data={timeSeriesData} margin={{ top: 5, right: 20, left: 0, bottom: 5 }}>
                <defs>
                  <linearGradient id="lossGradient" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#ef4444" stopOpacity={0.2} />
                    <stop offset="95%" stopColor="#ef4444" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                <XAxis
                  dataKey="timeLabel"
                  tick={{ fontSize: 10, fill: '#9ca3af' }}
                  tickFormatter={(v: string) => v.slice(11)}
                  interval="preserveStartEnd"
                />
                <YAxis
                  tick={{ fontSize: 10, fill: '#9ca3af' }}
                  tickFormatter={(v: number) => `${v}%`}
                  domain={[0, 'dataMax + 1']}
                />
                <Tooltip
                  contentStyle={{ fontSize: 12, borderRadius: 8 }}
                  formatter={(value: number) => [`${value}%`, t('chart.loss_rate_label')]}
                />
                <Area
                  type="monotone"
                  dataKey="lossRatePct"
                  stroke="#ef4444"
                  strokeWidth={2}
                  fill="url(#lossGradient)"
                  name={t('chart.loss_rate_label')}
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}
    </div>
  )
}
