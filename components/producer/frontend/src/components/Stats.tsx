/**
 * Stats.tsx — Real-time statistics charts for the HAMq Producer.
 *
 * Displays:
 *  - Messages per second (line chart — derived from sent_count deltas)
 *  - Buffer size over time (area chart)
 *  - Total sent / total failed counters
 *  - Connection status timeline
 *
 * All data arrives via the rateHistory prop which is updated by the WebSocket
 * stream in Dashboard.tsx.
 */

import React, { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import {
  ResponsiveContainer,
  LineChart,
  Line,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
} from 'recharts'
import type { ProducerStatus, RateDataPoint } from '../types'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function formatTime(unixMs: number): string {
  return new Date(unixMs).toLocaleTimeString('en-GB', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

interface ChartPoint {
  label: string
  sentPerSec: number
  buffered: number
}

// Convert raw cumulative sent_count to per-second delta
function toChartPoints(history: RateDataPoint[]): ChartPoint[] {
  return history.map((pt, i) => {
    const prev = i > 0 ? history[i - 1] : null
    const deltaMs = prev ? pt.time - prev.time : 1000
    const deltaSent = prev ? Math.max(0, pt.sent - prev.sent) : 0
    const sentPerSec = deltaMs > 0 ? (deltaSent / deltaMs) * 1000 : 0
    return {
      label: formatTime(pt.time),
      sentPerSec: Math.round(sentPerSec),
      buffered: pt.buffered,
    }
  })
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------
interface StatsProps {
  rateHistory: RateDataPoint[]
  status: ProducerStatus | null
}

export default function Stats({ rateHistory, status }: StatsProps) {
  const { t } = useTranslation()
  const chartData = useMemo(() => toChartPoints(rateHistory), [rateHistory])

  return (
    <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 shadow-sm p-5 space-y-5">
      {/* Header */}
      <h2 className="text-base font-semibold text-gray-900 dark:text-white">
        {t('chart.title')}
      </h2>

      {/* Counter tiles */}
      <div className="grid grid-cols-2 gap-3">
        <div className="bg-green-50 dark:bg-green-900/20 rounded-lg p-3">
          <p className="text-xs font-medium text-green-700 dark:text-green-400 uppercase tracking-wide">
            {t('chart.sent')}
          </p>
          <p className="mt-1 text-2xl font-bold text-green-800 dark:text-green-300 tabular-nums">
            {(status?.sent_count ?? 0).toLocaleString()}
          </p>
        </div>
        <div className="bg-yellow-50 dark:bg-yellow-900/20 rounded-lg p-3">
          <p className="text-xs font-medium text-yellow-700 dark:text-yellow-400 uppercase tracking-wide">
            {t('chart.buffered')}
          </p>
          <p className="mt-1 text-2xl font-bold text-yellow-800 dark:text-yellow-300 tabular-nums">
            {(status?.buffered_count ?? 0).toLocaleString()}
          </p>
        </div>
      </div>

      {/* Messages per second line chart */}
      <div>
        <p className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-2">
          Messages / second
        </p>
        <ResponsiveContainer width="100%" height={160}>
          <LineChart data={chartData} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
            <XAxis
              dataKey="label"
              tick={{ fontSize: 10 }}
              interval="preserveStartEnd"
              stroke="#9ca3af"
            />
            <YAxis
              tick={{ fontSize: 10 }}
              stroke="#9ca3af"
              allowDecimals={false}
              domain={[0, (dataMax: number) => Math.max(dataMax, Math.ceil((status?.frequency_hz ?? 0) * 1.2))]}
            />
            <Tooltip
              contentStyle={{ fontSize: '12px' }}
              formatter={(value: number) => [value.toLocaleString(), 'msg/s']}
            />
            <Line
              type="monotone"
              dataKey="sentPerSec"
              name={t('chart.sent')}
              stroke="#22c55e"
              strokeWidth={2}
              dot={false}
              isAnimationActive={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>

      {/* Buffer size area chart */}
      <div>
        <p className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-2">
          Buffer size
        </p>
        <ResponsiveContainer width="100%" height={120}>
          <AreaChart data={chartData} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
            <defs>
              <linearGradient id="bufferGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#f59e0b" stopOpacity={0.4} />
                <stop offset="95%" stopColor="#f59e0b" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
            <XAxis
              dataKey="label"
              tick={{ fontSize: 10 }}
              interval="preserveStartEnd"
              stroke="#9ca3af"
            />
            <YAxis tick={{ fontSize: 10 }} stroke="#9ca3af" allowDecimals={false} />
            <Tooltip
              contentStyle={{ fontSize: '12px' }}
              formatter={(value: number) => [value.toLocaleString(), 'buffered']}
            />
            <Legend wrapperStyle={{ fontSize: '11px' }} />
            <Area
              type="monotone"
              dataKey="buffered"
              name={t('chart.buffered')}
              stroke="#f59e0b"
              strokeWidth={2}
              fill="url(#bufferGrad)"
              dot={false}
              isAnimationActive={false}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>

      {/* Connection status summary */}
      <div className="flex items-center gap-2 text-sm">
        <span
          className={`h-2.5 w-2.5 rounded-full flex-shrink-0 ${
            status?.kafka_connected ? 'bg-green-500' : 'bg-red-400'
          }`}
        />
        <span className="text-gray-600 dark:text-gray-400">
          Kafka:{' '}
          <strong className={status?.kafka_connected ? 'text-green-700 dark:text-green-400' : 'text-red-600 dark:text-red-400'}>
            {status?.kafka_connected ? t('status.connected') : t('status.disconnected')}
          </strong>
        </span>
        {status?.frequency_hz != null && (
          <span className="ml-auto text-xs text-gray-400 dark:text-gray-500 font-mono tabular-nums">
            {t('status.frequency')}: {status.frequency_hz.toFixed(1)} Hz
          </span>
        )}
      </div>
    </div>
  )
}
