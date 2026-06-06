import React from 'react'
import { useTranslation } from 'react-i18next'
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
} from 'recharts'
import type { DataBusMetrics } from '../types'

export interface DataBusPoint {
  time: string
  lag: number
  producerRate: number
  readRate: number
  consumerReceived: number
}

type Trend = 'up' | 'down' | 'stable'

function TrendArrow({ trend }: { trend: Trend }) {
  const cls =
    trend === 'up' ? 'text-red-500'
    : trend === 'down' ? 'text-green-500'
    : 'text-gray-400 dark:text-gray-500'
  return (
    <span className={`text-base font-bold leading-none select-none ${cls}`}>
      {trend === 'up' ? '↑' : trend === 'down' ? '↓' : '→'}
    </span>
  )
}

interface MiniChartProps {
  label: string
  value: string
  unit: string
  trend: Trend
  data: DataBusPoint[]
  dataKey: keyof DataBusPoint
  color: string
  available: boolean
}

function MiniChart({ label, value, unit, trend, data, dataKey, color, available }: MiniChartProps) {
  return (
    <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 shadow-sm p-4">
      <div className="flex items-center justify-between mb-0.5">
        <p className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide leading-tight">
          {label}
        </p>
        {!available && (
          <span className="text-[10px] text-gray-400 dark:text-gray-500 bg-gray-100 dark:bg-gray-700 px-1.5 py-0.5 rounded">
            offline
          </span>
        )}
      </div>
      <div className="flex items-baseline gap-1.5 mb-2">
        <span className="text-2xl font-bold tabular-nums text-gray-900 dark:text-white">{value}</span>
        <span className="text-xs text-gray-500 dark:text-gray-400">{unit}</span>
        <TrendArrow trend={trend} />
      </div>
      <ResponsiveContainer width="100%" height={72}>
        <LineChart data={data} margin={{ top: 2, right: 4, bottom: 0, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" strokeOpacity={0.5} />
          <XAxis dataKey="time" hide />
          <YAxis hide allowDecimals={false} />
          <Tooltip
            contentStyle={{ fontSize: '11px', padding: '4px 8px' }}
            formatter={(v: number) => [v.toLocaleString(), label]}
            labelFormatter={() => ''}
          />
          <Line
            type="monotone"
            dataKey={dataKey as string}
            stroke={color}
            strokeWidth={2}
            dot={false}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}

interface DataBusChartsProps {
  history: DataBusPoint[]
  latest: DataBusMetrics | null
  lagTrend: Trend
  producerTrend: Trend
  readTrend: Trend
}

export default function DataBusCharts({
  history,
  latest,
  lagTrend,
  producerTrend,
  readTrend,
}: DataBusChartsProps) {
  const { t } = useTranslation()

  const lastPoint = history.length >= 2 ? history[history.length - 1] : null
  const readRateDisplay = lastPoint ? lastPoint.readRate.toLocaleString() : '0'

  return (
    <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
      <MiniChart
        label={t('databus.lag', 'Messages on Bus')}
        value={(latest?.lag ?? 0).toLocaleString()}
        unit={t('databus.msg', 'msg')}
        trend={lagTrend}
        data={history}
        dataKey="lag"
        color="#f59e0b"
        available={latest?.consumer_available ?? false}
      />
      <MiniChart
        label={t('databus.incoming', 'Incoming msg/s')}
        value={(latest?.producer_rate ?? 0).toFixed(1)}
        unit="msg/s"
        trend={producerTrend}
        data={history}
        dataKey="producerRate"
        color="#3b82f6"
        available={latest?.producer_available ?? false}
      />
      <MiniChart
        label={t('databus.read', 'Read msg/s')}
        value={readRateDisplay}
        unit="msg/s"
        trend={readTrend}
        data={history}
        dataKey="readRate"
        color="#10b981"
        available={latest?.consumer_available ?? false}
      />
    </div>
  )
}
