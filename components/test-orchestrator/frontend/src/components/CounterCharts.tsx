import React from 'react'
import { useTranslation } from 'react-i18next'
import { Line } from 'react-chartjs-2'
import {
  Chart,
  LineController,
  LineElement,
  PointElement,
  LinearScale,
  CategoryScale,
  Tooltip,
  Legend,
  Filler,
} from 'chart.js'
import type { ChartData, ChartOptions } from 'chart.js'

Chart.register(LineController, LineElement, PointElement, LinearScale, CategoryScale, Tooltip, Legend, Filler)

interface HistoryPoint {
  time: string
  sent: number
  received: number | null
  send_rate: number
  recv_rate: number
  missing_count: number
}

interface MissingEntry {
  number: number
  first_seen: string
}

interface Props {
  history: HistoryPoint[]
  missingSample: MissingEntry[]
  missingCount: number
  counterMax: number
  freqHz: number
}

function baseOptions(yMin: number, yMax: number | undefined, stepSize: number | undefined): ChartOptions<'line'> {
  return {
    responsive: true,
    maintainAspectRatio: false,
    animation: false,
    interaction: { mode: 'index', intersect: false },
    plugins: {
      legend: { position: 'top', labels: { boxWidth: 12, padding: 10, font: { size: 11 } } },
      tooltip: { bodyFont: { size: 11 }, titleFont: { size: 11 } },
    },
    scales: {
      x: {
        type: 'category',
        ticks: {
          maxTicksLimit: 7,
          maxRotation: 0,
          autoSkip: true,
          font: { size: 11 },
        },
        grid: { color: 'rgba(0,0,0,0.06)' },
      },
      y: {
        min: yMin,
        ...(yMax !== undefined ? { max: yMax } : {}),
        ticks: {
          ...(stepSize !== undefined ? { stepSize } : { maxTicksLimit: 6 }),
          font: { size: 11 },
        },
        grid: { color: 'rgba(0,0,0,0.06)' },
      },
    },
  }
}

function AreaChart({
  label,
  labels,
  datasets,
  yMin,
  yMax,
  stepSize,
}: {
  label: string
  labels: string[]
  datasets: ChartData<'line'>['datasets']
  yMin: number
  yMax?: number
  stepSize?: number
}) {
  return (
    <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 shadow-sm p-4">
      <p className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-3">
        {label}
      </p>
      <div style={{ height: 160 }}>
        <Line data={{ labels, datasets }} options={baseOptions(yMin, yMax, stepSize)} />
      </div>
    </div>
  )
}

export default function CounterCharts({ history, missingSample, missingCount, counterMax, freqHz }: Props) {
  const { t } = useTranslation()
  const labels = history.map(p => p.time)

  // Step sizes for 5 even dividers (6 tick marks including 0 and max)
  const counterStep = Math.ceil(counterMax / 5)
  const rateStep    = Math.max(1, Math.ceil(freqHz / 5))

  return (
    <div className="space-y-4">
      <AreaChart
        label={t('charts.counterValue')}
        labels={labels}
        datasets={[
          {
            label: t('charts.sent'),
            data: history.map(p => p.sent),
            borderColor: '#3b82f6',
            backgroundColor: 'rgba(59,130,246,0.08)',
            borderWidth: 2,
            pointRadius: 0,
            fill: true,
            tension: 0.3,
          },
          {
            label: t('charts.received'),
            data: history.map(p => p.received ?? null),
            borderColor: '#10b981',
            backgroundColor: 'rgba(16,185,129,0.08)',
            borderWidth: 2,
            pointRadius: 0,
            fill: true,
            tension: 0.3,
          },
        ]}
        yMin={0}
        yMax={counterMax}
        stepSize={counterStep}
      />

      <AreaChart
        label={t('charts.rate')}
        labels={labels}
        datasets={[
          {
            label: t('charts.sendRate'),
            data: history.map(p => p.send_rate),
            borderColor: '#3b82f6',
            backgroundColor: 'rgba(59,130,246,0.08)',
            borderWidth: 2,
            pointRadius: 0,
            fill: true,
            tension: 0.3,
          },
          {
            label: t('charts.recvRate'),
            data: history.map(p => p.recv_rate),
            borderColor: '#10b981',
            backgroundColor: 'rgba(16,185,129,0.08)',
            borderWidth: 2,
            pointRadius: 0,
            fill: true,
            tension: 0.3,
          },
        ]}
        yMin={0}
        yMax={freqHz}
        stepSize={rateStep}
      />

      <AreaChart
        label={t('charts.gaps')}
        labels={labels}
        datasets={[
          {
            label: t('charts.gaps'),
            data: history.map(p => p.missing_count),
            borderColor: '#ef4444',
            backgroundColor: 'rgba(239,68,68,0.08)',
            borderWidth: 2,
            pointRadius: 0,
            fill: true,
            tension: 0.3,
          },
        ]}
        yMin={0}
      />

      {/* Judge Panel */}
      <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 shadow-sm p-4">
        <p className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-3">
          {t('judge.title')}
        </p>
        {missingCount === 0 ? (
          <p className="text-sm font-medium text-green-600 dark:text-green-400">{t('judge.none')}</p>
        ) : (
          <>
            <p className="text-xs text-gray-500 dark:text-gray-400 mb-3">
              {t('judge.showing', { n: missingSample.length, total: missingCount })}
            </p>
            <div style={{ borderCollapse: 'collapse', width: '100%', display: 'table' }}>
              <div style={{ display: 'table-header-group', borderBottom: '1px solid #e5e7eb', color: '#9ca3af', fontSize: '11px', fontFamily: 'monospace' }}>
                <div style={{ display: 'table-row' }}>
                  <div style={{ display: 'table-cell', padding: '4px 24px 4px 0', fontWeight: 600 }}>Timestamp</div>
                  <div style={{ display: 'table-cell', padding: '4px 0', fontWeight: 600 }}>Fehlende Nummer</div>
                </div>
              </div>
              <div style={{ display: 'table-row-group' }}>
                {missingSample.map(entry => (
                  <div key={entry.number} style={{ display: 'table-row', borderBottom: '1px solid #f3f4f6', fontSize: '12px', fontFamily: 'monospace' }}>
                    <div style={{ display: 'table-cell', padding: '5px 24px 5px 0', color: '#6b7280' }}>{entry.first_seen}</div>
                    <div style={{ display: 'table-cell', padding: '5px 0', color: '#dc2626', fontWeight: 700 }}>{entry.number}</div>
                  </div>
                ))}
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
