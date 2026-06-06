import React, { useState, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { useApi } from '../hooks/useApi'
import type { ArbiterStatus, ReconcileReport } from '../types'

interface ReconcileControlProps {
  token: string | null
  status: ArbiterStatus | null
  onStatusChange: (status: ArbiterStatus) => void
  onReportReceived: (report: ReconcileReport) => void
  onToast: (message: string, type: 'success' | 'error' | 'info') => void
}

export default function ReconcileControl({
  token,
  status,
  onStatusChange,
  onReportReceived,
  onToast,
}: ReconcileControlProps) {
  const { t } = useTranslation()
  const api = useApi(token)

  const [reconciling, setReconciling] = useState(false)
  const [toggling, setToggling] = useState(false)
  const [intervalValue, setIntervalValue] = useState(2)
  const [lookbackValue, setLookbackValue] = useState(300)

  const handleReconcileNow = useCallback(async () => {
    setReconciling(true)
    try {
      const res = await api.post<ReconcileReport>('/api/reconcile')
      onReportReceived(res.data)
      const missing = res.data.total_missing
      if (missing > 0) {
        onToast(t('toast.reconcile_gaps').replace('{count}', String(missing)), 'error')
      } else {
        onToast(t('toast.reconcile_ok'), 'success')
      }
    } catch {
      onToast(t('errors.reconcile_failed'), 'error')
    } finally {
      setReconciling(false)
    }
  }, [api, onReportReceived, onToast, t])

  const handleToggle = useCallback(async () => {
    if (!status) return
    setToggling(true)
    try {
      const endpoint = status.running ? '/api/stop' : '/api/start'
      const res = await api.post<ArbiterStatus>(endpoint, {
        reconcile_interval_s: intervalValue,
        lookback_seconds: lookbackValue,
      })
      onStatusChange(res.data)
      if (status.running) {
        onToast(t('toast.stop_ok'), 'info')
      } else {
        onToast(t('toast.start_ok'), 'success')
      }
    } catch {
      onToast(status.running ? t('errors.stop_failed') : t('errors.start_failed'), 'error')
    } finally {
      setToggling(false)
    }
  }, [api, status, intervalValue, lookbackValue, onStatusChange, onToast, t])

  const isRunning = status?.running ?? false

  return (
    <div className="card space-y-5">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-gray-700">{t('controls.title')}</h3>
        <span className={`flex items-center gap-1.5 text-xs font-medium
          ${isRunning ? 'text-green-600' : 'text-gray-500'}`}>
          <span className={`w-2 h-2 rounded-full ${isRunning ? 'bg-green-500 animate-pulse' : 'bg-gray-400'}`} />
          {isRunning ? t('status.running') : t('status.stopped')}
        </span>
      </div>

      {/* Interval slider */}
      <div className="space-y-1.5">
        <div className="flex items-center justify-between">
          <label className="text-xs font-medium text-gray-600" htmlFor="interval-slider">
            {t('controls.interval_label')}
          </label>
          <span className="text-xs font-semibold text-brand-600 tabular-nums">
            {intervalValue}s
          </span>
        </div>
        <input
          id="interval-slider"
          type="range"
          min={1}
          max={60}
          step={1}
          value={intervalValue}
          onChange={(e) => setIntervalValue(Number(e.target.value))}
          className="w-full h-1.5 bg-gray-200 rounded-full appearance-none cursor-pointer accent-brand-600"
          disabled={isRunning}
        />
        <div className="flex justify-between text-xs text-gray-400">
          <span>1s</span>
          <span>60s</span>
        </div>
      </div>

      {/* Lookback window */}
      <div className="space-y-1.5">
        <label className="text-xs font-medium text-gray-600" htmlFor="lookback-input">
          {t('controls.lookback_label')}
        </label>
        <input
          id="lookback-input"
          type="number"
          min={10}
          max={86400}
          step={10}
          value={lookbackValue}
          onChange={(e) => setLookbackValue(Math.max(10, Number(e.target.value)))}
          className="input text-sm"
          disabled={isRunning}
        />
      </div>

      {/* Producer URLs info */}
      {status && (
        <div className="rounded-lg bg-gray-50 border border-gray-200 px-3 py-2">
          <p className="text-xs font-medium text-gray-500 mb-1">{t('controls.monitoring_label')}</p>
          <p className="text-xs text-gray-700 font-mono truncate">
            {status.producers_monitored} producer{status.producers_monitored !== 1 ? 's' : ''}
          </p>
        </div>
      )}

      {/* Buttons */}
      <div className="grid grid-cols-1 gap-2 pt-1">
        <button
          onClick={handleToggle}
          disabled={toggling || !status}
          className={isRunning ? 'btn-danger' : 'btn-success'}
        >
          {toggling && (
            <span className="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-t-transparent" />
          )}
          {toggling
            ? (isRunning ? t('controls.stopping') : t('controls.starting'))
            : (isRunning ? t('controls.stop') : t('controls.start'))
          }
        </button>

        <button
          onClick={handleReconcileNow}
          disabled={reconciling}
          className="btn-primary"
        >
          {reconciling && (
            <span className="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-white border-t-transparent" />
          )}
          {reconciling ? t('controls.reconciling') : t('controls.reconcile_now')}
        </button>
      </div>
    </div>
  )
}
