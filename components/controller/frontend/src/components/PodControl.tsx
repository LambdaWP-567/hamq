import React, { useState, useEffect, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import {
  RefreshCw, RotateCcw, Trash2, FileText, ChevronRight, AlertCircle
} from 'lucide-react'
import clsx from 'clsx'
import { formatDistanceToNow } from 'date-fns'
import { useApi, extractErrorMessage } from '../hooks/useApi'
import type { PodInfo, ClusterEvent, ControllerStatus } from '../types'

interface PodControlProps {
  liveStatus: ControllerStatus | null
}

interface ConfirmState {
  type: 'restart' | 'delete' | 'rolling'
  podName: string | null
}

function PodStatusBadge({ status, ready }: { status: string; ready: boolean }) {
  if (status === 'Running' && ready) {
    return <span className="badge-green">{status}</span>
  }
  if (status === 'Running' && !ready) {
    return <span className="badge-yellow">Not Ready</span>
  }
  if (status === 'Pending') {
    return <span className="badge-yellow">{status}</span>
  }
  if (status === 'Failed') {
    return <span className="badge-red">{status}</span>
  }
  return <span className="badge-gray">{status}</span>
}

const PodControl: React.FC<PodControlProps> = ({ liveStatus }) => {
  const { t } = useTranslation()
  const api = useApi()

  const [pods, setPods] = useState<PodInfo[]>([])
  const [loading, setLoading] = useState(false)
  const [actionLoading, setActionLoading] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)
  const [confirm, setConfirm] = useState<ConfirmState | null>(null)
  const [lastEvent, setLastEvent] = useState<ClusterEvent | null>(null)

  const fetchPods = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await api.listPods()
      setPods(data)
    } catch (err) {
      setError(extractErrorMessage(err))
    } finally {
      setLoading(false)
    }
  }, [api])

  // Sync pods from WebSocket live status
  useEffect(() => {
    if (liveStatus?.kafka_pods) {
      setPods(liveStatus.kafka_pods)
    }
  }, [liveStatus])

  // Initial fetch
  useEffect(() => {
    void fetchPods()
  }, [fetchPods])

  const handleRestart = async (podName: string) => {
    setConfirm({ type: 'restart', podName })
  }

  const handleDelete = async (podName: string) => {
    setConfirm({ type: 'delete', podName })
  }

  const handleRollingRestart = () => {
    setConfirm({ type: 'rolling', podName: null })
  }

  const executeConfirm = async () => {
    if (!confirm) return
    setConfirm(null)
    setError(null)
    setSuccess(null)

    const key = confirm.podName ?? 'rolling'
    setActionLoading(key)

    try {
      if (confirm.type === 'restart' && confirm.podName) {
        const event = await api.restartPod(confirm.podName)
        setLastEvent(event)
        setSuccess(t('pods.restartSuccess', { name: confirm.podName }))
      } else if (confirm.type === 'delete' && confirm.podName) {
        const event = await api.deletePod(confirm.podName)
        setLastEvent(event)
        setSuccess(t('pods.deleteSuccess', { name: confirm.podName }))
      } else if (confirm.type === 'rolling') {
        // Serial rolling restart
        for (const pod of pods) {
          await api.restartPod(pod.name)
          // Brief pause between restarts to avoid cascading failures
          await new Promise((resolve) => setTimeout(resolve, 2000))
        }
        setSuccess(t('pods.rollingRestart'))
      }
      // Refresh list after action
      await fetchPods()
    } catch (err) {
      setError(extractErrorMessage(err))
    } finally {
      setActionLoading(null)
    }
  }

  const clearMessages = () => {
    setError(null)
    setSuccess(null)
  }

  return (
    <div className="space-y-4">
      {/* Header row */}
      <div className="flex flex-col sm:flex-row sm:items-center gap-3">
        <div>
          <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">
            {t('pods.title')}
          </h2>
          <p className="text-sm text-gray-500 dark:text-gray-400">{t('pods.subtitle')}</p>
        </div>
        <div className="sm:ml-auto flex gap-2 flex-wrap">
          <button
            onClick={() => void handleRollingRestart()}
            disabled={loading || pods.length === 0 || actionLoading !== null}
            className="btn-secondary"
          >
            <RotateCcw className="w-4 h-4" />
            {t('pods.rollingRestart')}
          </button>
          <button
            onClick={() => void fetchPods()}
            disabled={loading}
            className="btn-secondary"
          >
            <RefreshCw className={clsx('w-4 h-4', loading && 'animate-spin')} />
            {t('pods.refresh')}
          </button>
        </div>
      </div>

      {/* Status messages */}
      {error && (
        <div className="flex items-start gap-2 p-3 rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 text-red-700 dark:text-red-400 text-sm">
          <AlertCircle className="w-4 h-4 mt-0.5 flex-shrink-0" />
          <span className="flex-1">{error}</span>
          <button onClick={clearMessages} className="flex-shrink-0 hover:opacity-70">×</button>
        </div>
      )}
      {success && (
        <div className="flex items-start gap-2 p-3 rounded-lg bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 text-green-700 dark:text-green-400 text-sm">
          <span className="flex-1">{success}</span>
          <button onClick={clearMessages} className="flex-shrink-0 hover:opacity-70">×</button>
        </div>
      )}

      {/* Last event detail */}
      {lastEvent && (
        <div className="p-3 rounded-lg bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 text-blue-700 dark:text-blue-300 text-xs font-mono">
          [{lastEvent.event_type}] {lastEvent.target} — {lastEvent.status}: {lastEvent.details}
        </div>
      )}

      {/* Table */}
      <div className="card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
            <thead className="bg-gray-50 dark:bg-gray-800/50">
              <tr>
                {[
                  t('pods.name'),
                  t('pods.status'),
                  t('pods.node'),
                  t('pods.restarts'),
                  t('pods.actions'),
                ].map((col) => (
                  <th
                    key={col}
                    className="px-4 py-3 text-left table-header"
                  >
                    {col}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
              {loading && pods.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-4 py-8 text-center text-gray-400 dark:text-gray-500 text-sm">
                    <RefreshCw className="w-5 h-5 animate-spin mx-auto mb-2" />
                    {t('common.loading')}
                  </td>
                </tr>
              ) : pods.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-4 py-8 text-center text-gray-400 dark:text-gray-500 text-sm">
                    {t('pods.noPodsFound')}
                  </td>
                </tr>
              ) : (
                pods.map((pod) => {
                  const isActing = actionLoading === pod.name
                  return (
                    <tr
                      key={pod.name}
                      className={clsx(
                        'hover:bg-gray-50 dark:hover:bg-gray-800/50 transition-colors',
                        isActing && 'opacity-60'
                      )}
                    >
                      <td className="px-4 py-3">
                        <span className="font-mono text-sm text-gray-900 dark:text-gray-100 flex items-center gap-1.5">
                          <ChevronRight className="w-3 h-3 text-gray-400" />
                          {pod.name}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <PodStatusBadge status={pod.status} ready={pod.ready} />
                      </td>
                      <td className="px-4 py-3 text-sm text-gray-600 dark:text-gray-300 font-mono">
                        {pod.node || '—'}
                      </td>
                      <td className="px-4 py-3 text-sm text-center">
                        <span
                          className={clsx(
                            'font-mono',
                            pod.restart_count > 0
                              ? 'text-amber-600 dark:text-amber-400'
                              : 'text-gray-500 dark:text-gray-400'
                          )}
                        >
                          {pod.restart_count}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-1.5">
                          <button
                            onClick={() => void handleRestart(pod.name)}
                            disabled={isActing || actionLoading !== null}
                            title={t('pods.restart')}
                            className="btn-secondary py-1 px-2 text-xs"
                          >
                            {isActing && actionLoading === pod.name ? (
                              <RefreshCw className="w-3 h-3 animate-spin" />
                            ) : (
                              <RotateCcw className="w-3 h-3" />
                            )}
                            {t('pods.restart')}
                          </button>
                          <button
                            onClick={() => void handleDelete(pod.name)}
                            disabled={isActing || actionLoading !== null}
                            title={t('pods.forceDelete')}
                            className="btn-danger py-1 px-2 text-xs"
                          >
                            <Trash2 className="w-3 h-3" />
                            {t('pods.forceDelete')}
                          </button>
                        </div>
                      </td>
                    </tr>
                  )
                })
              )}
            </tbody>
          </table>
        </div>

        {/* Footer count */}
        {pods.length > 0 && (
          <div className="px-4 py-2 border-t border-gray-100 dark:border-gray-800 text-xs text-gray-400 dark:text-gray-500">
            {pods.length} pod{pods.length !== 1 ? 's' : ''}
          </div>
        )}
      </div>

      {/* Confirmation Modal */}
      {confirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm">
          <div className="card max-w-md w-full p-6 shadow-2xl">
            <h3 className="text-base font-semibold text-gray-900 dark:text-gray-100 mb-2">
              {confirm.type === 'restart' && t('pods.restartConfirm', { name: confirm.podName })}
              {confirm.type === 'delete' && t('pods.deleteConfirm', { name: confirm.podName })}
              {confirm.type === 'rolling' && t('pods.rollingRestartConfirm')}
            </h3>
            {confirm.type === 'delete' && (
              <p className="text-sm text-amber-600 dark:text-amber-400 mb-4 flex items-start gap-2">
                <AlertCircle className="w-4 h-4 flex-shrink-0 mt-0.5" />
                This simulates an abrupt pod crash with grace period=0.
              </p>
            )}
            <div className="flex justify-end gap-3 mt-4">
              <button onClick={() => setConfirm(null)} className="btn-secondary">
                {t('common.cancel')}
              </button>
              <button
                onClick={() => void executeConfirm()}
                className={confirm.type === 'delete' ? 'btn-danger' : 'btn-primary'}
              >
                {t('common.confirm')}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default PodControl
