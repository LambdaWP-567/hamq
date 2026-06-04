import React, { useState, useEffect, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { RefreshCw, AlertTriangle, AlertCircle, CheckCircle2, Ban } from 'lucide-react'
import clsx from 'clsx'
import { useApi, extractErrorMessage } from '../hooks/useApi'
import type { NodeInfo, ClusterEvent, ControllerStatus } from '../types'

interface NodeControlProps {
  liveStatus: ControllerStatus | null
}

interface DrainConfirmState {
  nodeName: string
}

function NodeStatusBadge({ status, schedulable }: { status: string; schedulable: boolean }) {
  if (!schedulable) {
    return (
      <span className="badge-yellow flex items-center gap-1">
        <Ban className="w-3 h-3" />
        Scheduling Disabled
      </span>
    )
  }
  if (status === 'Ready') {
    return (
      <span className="badge-green flex items-center gap-1">
        <CheckCircle2 className="w-3 h-3" />
        Ready
      </span>
    )
  }
  return (
    <span className="badge-red flex items-center gap-1">
      <AlertCircle className="w-3 h-3" />
      {status}
    </span>
  )
}

const NodeControl: React.FC<NodeControlProps> = ({ liveStatus }) => {
  const { t } = useTranslation()
  const api = useApi()

  const [nodes, setNodes] = useState<NodeInfo[]>([])
  const [loading, setLoading] = useState(false)
  const [actionLoading, setActionLoading] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)
  const [drainConfirm, setDrainConfirm] = useState<DrainConfirmState | null>(null)
  const [lastEvent, setLastEvent] = useState<ClusterEvent | null>(null)

  const fetchNodes = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await api.listNodes()
      setNodes(data)
    } catch (err) {
      setError(extractErrorMessage(err))
    } finally {
      setLoading(false)
    }
  }, [api])

  // Sync from WebSocket
  useEffect(() => {
    if (liveStatus?.nodes) {
      setNodes(liveStatus.nodes)
    }
  }, [liveStatus])

  useEffect(() => {
    void fetchNodes()
  }, [fetchNodes])

  const handleCordon = async (nodeName: string) => {
    setActionLoading(nodeName)
    setError(null)
    setSuccess(null)
    try {
      const event = await api.cordonNode(nodeName)
      setLastEvent(event)
      setSuccess(t('nodes.cordonSuccess', { name: nodeName }))
      await fetchNodes()
    } catch (err) {
      setError(extractErrorMessage(err))
    } finally {
      setActionLoading(null)
    }
  }

  const handleUncordon = async (nodeName: string) => {
    setActionLoading(nodeName)
    setError(null)
    setSuccess(null)
    try {
      const event = await api.uncordonNode(nodeName)
      setLastEvent(event)
      setSuccess(t('nodes.uncordonSuccess', { name: nodeName }))
      await fetchNodes()
    } catch (err) {
      setError(extractErrorMessage(err))
    } finally {
      setActionLoading(null)
    }
  }

  const handleDrainConfirm = async () => {
    if (!drainConfirm) return
    const { nodeName } = drainConfirm
    setDrainConfirm(null)
    setActionLoading(nodeName)
    setError(null)
    setSuccess(null)
    try {
      const event = await api.drainNode(nodeName)
      setLastEvent(event)
      setSuccess(t('nodes.drainSuccess', { name: nodeName }))
      await fetchNodes()
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
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center gap-3">
        <div>
          <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">
            {t('nodes.title')}
          </h2>
          <p className="text-sm text-gray-500 dark:text-gray-400">{t('nodes.subtitle')}</p>
        </div>
        <button
          onClick={() => void fetchNodes()}
          disabled={loading}
          className="btn-secondary sm:ml-auto"
        >
          <RefreshCw className={clsx('w-4 h-4', loading && 'animate-spin')} />
          {t('nodes.refresh')}
        </button>
      </div>

      {/* Drain warning banner */}
      <div className="flex items-start gap-3 p-3 rounded-lg bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-700 text-amber-800 dark:text-amber-300 text-sm">
        <AlertTriangle className="w-4 h-4 flex-shrink-0 mt-0.5" />
        <p>{t('nodes.drainWarning')}</p>
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

      {/* Last event */}
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
                  t('nodes.name'),
                  t('nodes.status'),
                  t('nodes.roles'),
                  t('nodes.actions'),
                ].map((col) => (
                  <th key={col} className="px-4 py-3 text-left table-header">
                    {col}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
              {loading && nodes.length === 0 ? (
                <tr>
                  <td colSpan={4} className="px-4 py-8 text-center text-gray-400 text-sm">
                    <RefreshCw className="w-5 h-5 animate-spin mx-auto mb-2" />
                    {t('common.loading')}
                  </td>
                </tr>
              ) : nodes.length === 0 ? (
                <tr>
                  <td colSpan={4} className="px-4 py-8 text-center text-gray-400 text-sm">
                    {t('nodes.noNodesFound')}
                  </td>
                </tr>
              ) : (
                nodes.map((node) => {
                  const isActing = actionLoading === node.name
                  return (
                    <tr
                      key={node.name}
                      className={clsx(
                        'hover:bg-gray-50 dark:hover:bg-gray-800/50 transition-colors',
                        isActing && 'opacity-60'
                      )}
                    >
                      <td className="px-4 py-3 font-mono text-sm text-gray-900 dark:text-gray-100">
                        {node.name}
                      </td>
                      <td className="px-4 py-3">
                        <NodeStatusBadge status={node.status} schedulable={node.schedulable} />
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex flex-wrap gap-1">
                          {node.roles.map((role) => (
                            <span key={role} className="badge-blue text-xs">{role}</span>
                          ))}
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-1.5 flex-wrap">
                          {node.schedulable ? (
                            <button
                              onClick={() => void handleCordon(node.name)}
                              disabled={isActing || actionLoading !== null}
                              className="btn-secondary py-1 px-2 text-xs"
                            >
                              {isActing ? (
                                <RefreshCw className="w-3 h-3 animate-spin" />
                              ) : (
                                <Ban className="w-3 h-3" />
                              )}
                              {t('nodes.cordon')}
                            </button>
                          ) : (
                            <button
                              onClick={() => void handleUncordon(node.name)}
                              disabled={isActing || actionLoading !== null}
                              className="btn-primary py-1 px-2 text-xs"
                            >
                              {isActing ? (
                                <RefreshCw className="w-3 h-3 animate-spin" />
                              ) : (
                                <CheckCircle2 className="w-3 h-3" />
                              )}
                              {t('nodes.uncordon')}
                            </button>
                          )}
                          <button
                            onClick={() => setDrainConfirm({ nodeName: node.name })}
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
                })
              )}
            </tbody>
          </table>
        </div>
        {nodes.length > 0 && (
          <div className="px-4 py-2 border-t border-gray-100 dark:border-gray-800 text-xs text-gray-400">
            {nodes.length} node{nodes.length !== 1 ? 's' : ''}
          </div>
        )}
      </div>

      {/* Drain Confirmation Modal */}
      {drainConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm">
          <div className="card max-w-md w-full p-6 shadow-2xl">
            <div className="flex items-start gap-3 mb-4">
              <div className="flex-shrink-0 w-10 h-10 rounded-full bg-red-100 dark:bg-red-900/30 flex items-center justify-center">
                <AlertTriangle className="w-5 h-5 text-red-600 dark:text-red-400" />
              </div>
              <div>
                <h3 className="text-base font-semibold text-gray-900 dark:text-gray-100">
                  {t('nodes.drainConfirm', { name: drainConfirm.nodeName })}
                </h3>
                <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
                  {t('nodes.drainWarning')}
                </p>
              </div>
            </div>
            <div className="p-3 rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 text-red-700 dark:text-red-400 text-sm mb-4">
              Node: <span className="font-mono font-semibold">{drainConfirm.nodeName}</span>
            </div>
            <div className="flex justify-end gap-3">
              <button onClick={() => setDrainConfirm(null)} className="btn-secondary">
                {t('common.cancel')}
              </button>
              <button onClick={() => void handleDrainConfirm()} className="btn-danger">
                {t('nodes.drain')}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default NodeControl
