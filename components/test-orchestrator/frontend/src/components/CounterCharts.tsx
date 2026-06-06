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
  Legend,
} from 'recharts'

interface HistoryPoint {
  time: string
  sent: number
  received: number | null
  send_rate: number
  recv_rate: number
  missing_count: number
}

interface Props {
  history: HistoryPoint[]
  missingSample: number[]
  missingCount: number
}

function MiniChart({
  label,
  data,
  lines,
}: {
  label: string
  data: HistoryPoint[]
  lines: { key: string; color: string; name: string }[]
}) {
  return (
    <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 shadow-sm p-4">
      <p className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-2">
        {label}
      </p>
      <ResponsiveContainer width="100%" height={80}>
        <LineChart data={data} margin={{ top: 2, right: 4, bottom: 0, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" strokeOpacity={0.5} />
          <XAxis dataKey="time" hide />
          <YAxis hide allowDecimals={false} />
          <Tooltip
            contentStyle={{ fontSize: '11px', padding: '4px 8px' }}
            labelFormatter={() => ''}
          />
          {lines.map(l => (
            <Line
              key={l.key}
              type="monotone"
              dataKey={l.key}
              stroke={l.color}
              strokeWidth={2}
              dot={false}
              isAnimationActive={false}
              name={l.name}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}

export default function CounterCharts({ history, missingSample, missingCount }: Props) {
  const { t } = useTranslation()

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <MiniChart
          label={t('charts.counterValue')}
          data={history}
          lines={[
            { key: 'sent', color: '#3b82f6', name: t('charts.sent') },
            { key: 'received', color: '#10b981', name: t('charts.received') },
          ]}
        />
        <MiniChart
          label={t('charts.rate')}
          data={history}
          lines={[
            { key: 'send_rate', color: '#3b82f6', name: t('charts.sendRate') },
            { key: 'recv_rate', color: '#10b981', name: t('charts.recvRate') },
          ]}
        />
        <MiniChart
          label={t('charts.gaps')}
          data={history}
          lines={[{ key: 'missing_count', color: '#ef4444', name: t('charts.gaps') }]}
        />
      </div>

      {/* Judge Panel */}
      <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 shadow-sm p-4">
        <p className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-2">
          {t('judge.title')}
        </p>
        {missingCount === 0 ? (
          <p className="text-sm font-medium text-green-600 dark:text-green-400">{t('judge.none')}</p>
        ) : (
          <>
            <p className="text-xs text-gray-500 dark:text-gray-400 mb-2">
              {t('judge.showing', { n: missingSample.length, total: missingCount })}
            </p>
            <div className="flex flex-wrap gap-1.5">
              {missingSample.map(n => (
                <span
                  key={n}
                  className="inline-flex items-center px-2 py-0.5 rounded text-xs font-mono font-medium bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400"
                >
                  {n}
                </span>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  )
}
