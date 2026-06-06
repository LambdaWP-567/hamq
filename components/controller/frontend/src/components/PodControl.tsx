import React, { useState, useEffect, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { RefreshCw, RotateCcw, Trash2, ChevronRight, AlertCircle } from 'lucide-react'
import clsx from 'clsx'
import { useApi, extractErrorMessage } from '../hooks/useApi'
import { useToast } from '../hooks/useToast'
import type { PodInfo, ControllerStatus } from '../types'

interface PodControlProps {
  liveStatus: ControllerStatus | null
}

function PodStatusBadge({ status, ready }: { status: string; ready: boolean }) {
  if (status === 'Running' && ready)  return <span className="badge-green">{status}</span>
  if (status === 'Running' && !ready) return <span className="badge-yellow">Not Ready</span>
  if (status === 'Pending')           return <span className="badge-yellow">{status}</span>
  if (status === 'Failed')            return <span className="badge-red">{status}</span>
  return <span className="badge-gray">{status}</span>
}

const PodControl: React.FC<PodControlProps> = ({ liveStatus }) => {
  const { t } = useTranslation()
  const api = useApi()
  const { showToast } = useToast()

  const [pods, setPods] = useState<PodInfo[]>([])
  const [loading, setLoading] = useState(false)
  const [actionLoading, setActionLoading] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const fetchPods = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setPods(await api.listPods())
    } catch (err) {
      setError(extractErrorMessage(err))
    } finally {
      setLoading(false)
    }
  }, [api])

  useEffect(() => {
    if (liveStatus?.kafka_pods) setPods(liveStatus.kafka_pods)
  }, [liveStatus])

  useEffect(() => { void fetchPods() }, [fetchPods])

  const handleRestart = async (podName: string) => {
    setActionLoading(podName)
    setError(null)
    try {
      await api.restartPod(podName)
      showToast(t('pods.restartSuccess', { name: podName }))
      await fetchPods()
    } catch (err) {
      setError(extractErrorMessage(err))
      showToast(extractErrorMessage(err), 'error')
    } finally {
      setActionLoading(null)
    }
  }

  const handleDelete = async (podName: string) => {
    setActionLoading(podName)
    setError(null)
    try {
      await api.deletePod(podName)
      showToast(t('pods.deleteSuccess', { name: podName }), 'info')
      await fetchPods()
    } catch (err) {
      setError(extractErrorMessage(err))
      showToast(extractErrorMessage(err), 'error')
    } finally {
      setActionLoading(null)
    }
  }

  const handleRollingRestart = async () => {
    setActionLoading('rolling')
    setError(null)
    try {
      for (const pod of pods) {
        await api.restartPod(pod.name)
        await new Promise(r => setTimeout(r, 2000))
      }
      showToast(t('pods.rollingRestart'))
      await fetchPods()
    } catch (err) {
      setError(extractErrorMessage(err))
      showToast(extractErrorMessage(err), 'error')
    } finally {
      setActionLoading(null)
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-col sm:flex-row sm:items-center gap-3">
        <div>
          <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">{t('pods.title')}</h2>
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
          <button onClick={() => void fetchPods()} disabled={loading} className="btn-secondary">
            <RefreshCw className={clsx('w-4 h-4', loading && 'animate-spin')} />
            {t('pods.refresh')}
          </button>
        </div>
      </div>

      {error && (
        <div className="flex items-start gap-2 p-3 rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 text-red-700 dark:text-red-400 text-sm">
          <AlertCircle className="w-4 h-4 mt-0.5 flex-shrink-0" />
          <span className="flex-1">{error}</span>
          <button onClick={() => setError(null)} className="flex-shrink-0 hover:opacity-70">×</button>
        </div>
      )}

      <div className="card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
            <thead className="bg-gray-50 dark:bg-gray-800/50">
              <tr>
                {[t('pods.name'), t('pods.status'), t('pods.node'), t('pods.restarts'), t('pods.actions')].map(col => (
                  <th key={col} className="px-4 py-3 text-left table-header">{col}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
              {loading && pods.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-4 py-8 text-center text-gray-400 text-sm">
                    <RefreshCw className="w-5 h-5 animate-spin mx-auto mb-2" />
                    {t('common.loading')}
                  </td>
                </tr>
              ) : pods.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-4 py-8 text-center text-gray-400 text-sm">{t('pods.noPodsFound')}</td>
                </tr>
              ) : pods.map(pod => {
                const isActing = actionLoading === pod.name || actionLoading === 'rolling'
                return (
                  <tr key={pod.name} className={clsx('hover:bg-gray-50 dark:hover:bg-gray-800/50 transition-colors', isActing && 'opacity-60')}>
                    <td className="px-4 py-3">
                      <span className="font-mono text-sm text-gray-900 dark:text-gray-100 flex items-center gap-1.5">
                        <ChevronRight className="w-3 h-3 text-gray-400" />
                        {pod.name}
                      </span>
                    </td>
                    <td className="px-4 py-3"><PodStatusBadge status={pod.status} ready={pod.ready} /></td>
                    <td className="px-4 py-3 text-sm text-gray-600 dark:text-gray-300 font-mono">{pod.node || '—'}</td>
                    <td className="px-4 py-3 text-sm text-center">
                      <span className={clsx('font-mono', pod.restart_count > 0 ? 'text-amber-600 dark:text-amber-400' : 'text-gray-500 dark:text-gray-400')}>
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
                          {isActing && actionLoading === pod.name
                            ? <RefreshCw className="w-3 h-3 animate-spin" />
                            : <RotateCcw className="w-3 h-3" />}
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
              })}
            </tbody>
          </table>
        </div>
        {pods.length > 0 && (
          <div className="px-4 py-2 border-t border-gray-100 dark:border-gray-800 text-xs text-gray-400">
            {pods.length} pod{pods.length !== 1 ? 's' : ''}
          </div>
        )}
      </div>
    </div>
  )
}

export default PodControl
