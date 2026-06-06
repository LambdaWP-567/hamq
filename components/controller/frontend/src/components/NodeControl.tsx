import React, { useState, useEffect, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { RefreshCw, AlertTriangle, AlertCircle, CheckCircle2, Ban } from 'lucide-react'
import clsx from 'clsx'
import { useApi, extractErrorMessage } from '../hooks/useApi'
import { useToast } from '../hooks/useToast'
import type { NodeInfo, ControllerStatus } from '../types'

interface NodeControlProps {
  liveStatus: ControllerStatus | null
}

function NodeStatusBadge({ status, schedulable }: { status: string; schedulable: boolean }) {
  if (!schedulable) return <span className="badge-yellow flex items-center gap-1"><Ban className="w-3 h-3" />Scheduling Disabled</span>
  if (status === 'Ready') return <span className="badge-green flex items-center gap-1"><CheckCircle2 className="w-3 h-3" />Ready</span>
  return <span className="badge-red flex items-center gap-1"><AlertCircle className="w-3 h-3" />{status}</span>
}

const NodeControl: React.FC<NodeControlProps> = ({ liveStatus }) => {
  const { t } = useTranslation()
  const api = useApi()
  const { showToast } = useToast()

  const [nodes, setNodes] = useState<NodeInfo[]>([])
  const [loading, setLoading] = useState(false)
  const [actionLoading, setActionLoading] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const fetchNodes = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setNodes(await api.listNodes())
    } catch (err) {
      setError(extractErrorMessage(err))
    } finally {
      setLoading(false)
    }
  }, [api])

  useEffect(() => { if (liveStatus?.nodes) setNodes(liveStatus.nodes) }, [liveStatus])
  useEffect(() => { void fetchNodes() }, [fetchNodes])

  const exec = async (label: string, fn: () => Promise<unknown>, type: 'success' | 'info' = 'success') => {
    setActionLoading(label)
    setError(null)
    try {
      await fn()
      showToast(label, type)
      await fetchNodes()
    } catch (err) {
      const msg = extractErrorMessage(err)
      setError(msg)
      showToast(msg, 'error')
    } finally {
      setActionLoading(null)
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-col sm:flex-row sm:items-center gap-3">
        <div>
          <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">{t('nodes.title')}</h2>
          <p className="text-sm text-gray-500 dark:text-gray-400">{t('nodes.subtitle')}</p>
        </div>
        <button onClick={() => void fetchNodes()} disabled={loading} className="btn-secondary sm:ml-auto">
          <RefreshCw className={clsx('w-4 h-4', loading && 'animate-spin')} />
          {t('nodes.refresh')}
        </button>
      </div>

      <div className="flex items-start gap-3 p-3 rounded-lg bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-700 text-amber-800 dark:text-amber-300 text-sm">
        <AlertTriangle className="w-4 h-4 flex-shrink-0 mt-0.5" />
        <p>{t('nodes.drainWarning')}</p>
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
                {[t('nodes.name'), t('nodes.status'), t('nodes.roles'), t('nodes.actions')].map(col => (
                  <th key={col} className="px-4 py-3 text-left table-header">{col}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
              {loading && nodes.length === 0 ? (
                <tr><td colSpan={4} className="px-4 py-8 text-center text-gray-400 text-sm"><RefreshCw className="w-5 h-5 animate-spin mx-auto mb-2" />{t('common.loading')}</td></tr>
              ) : nodes.length === 0 ? (
                <tr><td colSpan={4} className="px-4 py-8 text-center text-gray-400 text-sm">{t('nodes.noNodesFound')}</td></tr>
              ) : nodes.map(node => {
                const isActing = actionLoading === node.name
                return (
                  <tr key={node.name} className={clsx('hover:bg-gray-50 dark:hover:bg-gray-800/50 transition-colors', isActing && 'opacity-60')}>
                    <td className="px-4 py-3 font-mono text-sm text-gray-900 dark:text-gray-100">{node.name}</td>
                    <td className="px-4 py-3"><NodeStatusBadge status={node.status} schedulable={node.schedulable} /></td>
                    <td className="px-4 py-3">
                      <div className="flex flex-wrap gap-1">
                        {node.roles.map(role => <span key={role} className="badge-blue text-xs">{role}</span>)}
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-1.5 flex-wrap">
                        {node.schedulable ? (
                          <button
                            onClick={() => void exec(t('nodes.cordonSuccess', { name: node.name }), () => api.cordonNode(node.name))}
                            disabled={isActing || actionLoading !== null}
                            className="btn-secondary py-1 px-2 text-xs"
                          >
                            {isActing ? <RefreshCw className="w-3 h-3 animate-spin" /> : <Ban className="w-3 h-3" />}
                            {t('nodes.cordon')}
                          </button>
                        ) : (
                          <button
                            onClick={() => void exec(t('nodes.uncordonSuccess', { name: node.name }), () => api.uncordonNode(node.name))}
                            disabled={isActing || actionLoading !== null}
                            className="btn-primary py-1 px-2 text-xs"
                          >
                            {isActing ? <RefreshCw className="w-3 h-3 animate-spin" /> : <CheckCircle2 className="w-3 h-3" />}
                            {t('nodes.uncordon')}
                          </button>
                        )}
                        <button
                          onClick={() => void exec(t('nodes.drainSuccess', { name: node.name }), () => api.drainNode(node.name), 'info')}
                          disabled={isActing || actionLoading !== null}
                          className="btn-danger py-1 px-2 text-xs"
                        >
                          <AlertTriangle className="w-3 h-3" />
                          {t('nodes.drain')}
                        </button>
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
        {nodes.length > 0 && (
          <div className="px-4 py-2 border-t border-gray-100 dark:border-gray-800 text-xs text-gray-400">
            {nodes.length} node{nodes.length !== 1 ? 's' : ''}
          </div>
        )}
      </div>
    </div>
  )
}

export default NodeControl
