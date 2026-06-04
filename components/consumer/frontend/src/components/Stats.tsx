/**
 * Stats.tsx — Real-time statistics charts for the HAMq Consumer.
 *
 * Displays:
 *  - Messages per second receive rate (line chart)
 *  - Gaps detected (derived from missing sequences via lag_estimate proxy)
 *  - Latency histogram placeholder with receive rate distribution
 *  - Total received counter and consumer lag
 *
 * All data arrives via rateHistory (populated by WebSocket in Dashboard).
 */

import React, { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import {
  ResponsiveContainer,
  LineChart,
  Line,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
} from 'recharts'
import type { ConsumerStatus, ReceiveRatePoint } from '../types'

// ---------------------------------------------------------------------------
// Latency bucket helper — bucket the recent per-second rates into a histogram
// ---------------------------------------------------------------------------
interface LatencyBucket {
  range: string
  count: number
}

function buildHistogram(history: ReceiveRatePoint[]): LatencyBucket[] {
  const buckets: Record<string, number> = {
    '0': 0, '1-10': 0, '11-50': 0, '51-200': 0, '201-500': 0, '500+': 0,
  }
  for (const pt of history) {
    const r = pt.rate
    if (r === 0) buckets['0']++
    else if (r <= 10) buckets['1-10']++
    else if (r <= 50) buckets['11-50']++
    else if (r <= 200) buckets['51-200']++
    else if (r <= 500) buckets['201-500']++
    else buckets['500+']++
  }
  return Object.entries(buckets).map(([range, count]) => ({ range, count }))
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------
interface StatsProps {
  rateHistory: ReceiveRatePoint[]
  status: ConsumerStatus | null
}

export default function Stats({ rateHistory, status }: StatsProps) {
  const { t } = useTranslation()
  const histogram = useMemo(() => buildHistogram(rateHistory), [rateHistory])

  return (
    <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 shadow-sm p-5 space-y-5">
      {/* Header */}
      <h2 className="text-base font-semibold text-gray-900 dark:text-white">
        Statistics
      </h2>

      {/* Counter tiles */}
      <div className="grid grid-cols-2 gap-3">
        <div className="bg-blue-50 dark:bg-blue-900/20 rounded-lg p-3">
          <p className="text-xs font-medium text-blue-700 dark:text-blue-400 uppercase tracking-wide">
            {t('status.received')}
          </p>
          <p className="mt-1 text-2xl font-bold text-blue-800 dark:text-blue-300 tabular-nums">
            {(status?.received_count ?? 0).toLocaleString()}
          </p>
        </div>
        <div className={`rounded-lg p-3 ${
          (status?.lag_estimate ?? 0) > 1000
            ? 'bg-yellow-50 dark:bg-yellow-900/20'
            : 'bg-gray-50 dark:bg-gray-700/50'}`}>
          <p className={`text-xs font-medium uppercase tracking-wide ${
            (status?.lag_estimate ?? 0) > 1000
              ? 'text-yellow-700 dark:text-yellow-400'
              : 'text-gray-600 dark:text-gray-400'
          }`}>
            {t('status.lag')}
          </p>
          <p className={`mt-1 text-2xl font-bold tabular-nums ${
            (status?.lag_estimate ?? 0) > 1000
              ? 'text-yellow-800 dark:text-yellow-300'
              : 'text-gray-800 dark:text-gray-200'
          }`}>
            {(status?.lag_estimate ?? 0).toLocaleString()}
          </p>
        </div>
      </div>

      {/* Receive rate line chart */}
      <div>
        <p className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-2">
          {t('chart.receive_rate')}
        </p>
        <ResponsiveContainer width="100%" height={160}>
          <LineChart data={rateHistory} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
            <XAxis
              dataKey="time"
              tick={{ fontSize: 10 }}
              interval="preserveStartEnd"
              stroke="#9ca3af"
            />
            <YAxis tick={{ fontSize: 10 }} stroke="#9ca3af" allowDecimals={false} />
            <Tooltip
              contentStyle={{ fontSize: '12px' }}
              formatter={(value: number) => [value.toLocaleString(), 'msg/s']}
            />
            <Line
              type="monotone"
              dataKey="rate"
              name={t('chart.messages_per_second')}
              stroke="#3b82f6"
              strokeWidth={2}
              dot={false}
              isAnimationActive={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>

      {/* Rate histogram — approximates latency distribution */}
      <div>
        <p className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-2">
          Rate Distribution (msg/s buckets)
        </p>
        <ResponsiveContainer width="100%" height={120}>
          <BarChart data={histogram} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
            <XAxis dataKey="range" tick={{ fontSize: 10 }} stroke="#9ca3af" />
            <YAxis tick={{ fontSize: 10 }} stroke="#9ca3af" allowDecimals={false} />
            <Tooltip contentStyle={{ fontSize: '12px' }} />
            <Bar
              dataKey="count"
              name="Samples"
              fill="#3b82f6"
              radius={[2, 2, 0, 0]}
              isAnimationActive={false}
            />
          </BarChart>
        </ResponsiveContainer>
      </div>

      {/* Checksum errors indicator */}
      <div className="flex items-center justify-between text-sm">
        <span className="text-gray-600 dark:text-gray-400">{t('status.checksum_errors')}</span>
        <span className={`font-mono font-semibold tabular-nums ${
          (status?.checksum_errors ?? 0) > 0
            ? 'text-red-600 dark:text-red-400'
            : 'text-gray-700 dark:text-gray-300'
        }`}>
          {(status?.checksum_errors ?? 0).toLocaleString()}
        </span>
      </div>
    </div>
  )
}
