/**
 * Dashboard.tsx — Main controller dashboard.
 *
 * Tabs: Pods | Nodes | Chaos | Network
 * Each tab renders the relevant control panel component.
 * Real-time status is streamed via WebSocket from the backend.
 */

import React, { useState, useEffect, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { Activity, Server, Zap, Network, RefreshCw, AlertTriangle, CheckCircle } from 'lucide-react'
import clsx from 'clsx'
import { useApi } from '../hooks/useApi'
import { useWebSocket } from '../hooks/useWebSocket'
import type { ControllerStatus } from '../types'
import PodControl from './PodControl'
import NodeControl from './NodeControl'
import ChaosControl from './ChaosControl'
import NetworkControl from './NetworkControl'

type TabId = 'pods' | 'nodes' | 'chaos' | 'network'

interface TabDef {
  id: TabId
  labelKey: string
  icon: React.ReactNode
}

const TABS: TabDef[] = [
  { id: 'pods',    labelKey: 'tabs.pods',    icon: <Server    className="w-4 h-4" /> },
  { id: 'nodes',   labelKey: 'tabs.nodes',   icon: <Activity  className="w-4 h-4" /> },
  { id: 'chaos',   labelKey: 'tabs.chaos',   icon: <Zap       className="w-4 h-4" /> },
  { id: 'network', labelKey: 'tabs.network', icon: <Network   className="w-4 h-4" /> },
]

const Dashboard: React.FC = () => {
  const { t } = useTranslation()
  const api = useApi()
  const { lastMessage } = useWebSocket()

  const [status, setStatus]   = useState<ControllerStatus | null>(null)
  const [activeTab, setActiveTab] = useState<TabId>('pods')
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState<string | null>(null)

  const fetchStatus = useCallback(async () => {
    try {
      const data = await api.getStatus()
      setStatus(data)
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Unknown error')
    } finally {
      setLoading(false)
    }
  }, [api])

  // Initial load
  useEffect(() => { fetchStatus() }, [fetchStatus])

  // Update on WebSocket push
  useEffect(() => {
    if (lastMessage) {
      setStatus(lastMessage)
    }
  }, [lastMessage])

  const podCount  = status?.kafka_pods?.length  ?? 0
  const nodeCount = status?.nodes?.length        ?? 0
  const partCount = status?.active_partitions?.length ?? 0
  const k8sOk     = status?.k8s_connected        ?? false

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900">
      {/* ── Header ────────────────────────────────────────────────── */}
      <header className="bg-white dark:bg-gray-800 shadow-sm border-b border-gray-200 dark:border-gray-700">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Zap className="w-7 h-7 text-orange-500" />
            <div>
              <h1 className="text-xl font-bold text-gray-900 dark:text-white">
                {t('header.title', 'HAMq Controller')}
              </h1>
              <p className="text-xs text-gray-500 dark:text-gray-400">
                {t('header.subtitle', 'Cluster lifecycle & chaos engineering')}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            {/* K8s connection indicator */}
            <span className={clsx(
              'flex items-center gap-1.5 text-sm font-medium px-3 py-1 rounded-full',
              k8sOk
                ? 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400'
                : 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400'
            )}>
              {k8sOk
                ? <CheckCircle className="w-3.5 h-3.5" />
                : <AlertTriangle className="w-3.5 h-3.5" />}
              {k8sOk ? t('status.connected', 'K8s Connected') : t('status.disconnected', 'K8s Disconnected')}
            </span>
            <button
              onClick={fetchStatus}
              className="p-2 rounded-lg text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors"
              title={t('actions.refresh', 'Refresh')}
            >
              <RefreshCw className="w-4 h-4" />
            </button>
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6 space-y-6">
        {/* ── Summary Cards ─────────────────────────────────────── */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          {[
            { label: t('cards.pods',       'Kafka Pods'),     value: podCount,  color: 'blue'   },
            { label: t('cards.nodes',      'Nodes'),          value: nodeCount, color: 'purple' },
            { label: t('cards.partitions', 'Net Partitions'), value: partCount, color: partCount > 0 ? 'red' : 'gray' },
            { label: t('cards.chaos',      'Chaos Active'),   value: status?.chaos_enabled ? t('yes', 'Yes') : t('no', 'No'), color: status?.chaos_enabled ? 'orange' : 'gray' },
          ].map(({ label, value, color }) => (
            <div key={label} className="bg-white dark:bg-gray-800 rounded-xl p-4 shadow-sm border border-gray-200 dark:border-gray-700">
              <p className="text-xs text-gray-500 dark:text-gray-400 mb-1">{label}</p>
              <p className={clsx('text-2xl font-bold', {
                'text-blue-600 dark:text-blue-400':   color === 'blue',
                'text-purple-600 dark:text-purple-400': color === 'purple',
                'text-red-600 dark:text-red-400':     color === 'red',
                'text-orange-500 dark:text-orange-400': color === 'orange',
                'text-gray-600 dark:text-gray-400':   color === 'gray',
              })}>{loading ? '…' : value}</p>
            </div>
          ))}
        </div>

        {error && (
          <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-xl p-4 flex gap-2 text-red-700 dark:text-red-400 text-sm">
            <AlertTriangle className="w-4 h-4 flex-shrink-0 mt-0.5" />
            {error}
          </div>
        )}

        {/* ── Tab Navigation ────────────────────────────────────── */}
        <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 overflow-hidden">
          <div className="flex border-b border-gray-200 dark:border-gray-700 overflow-x-auto">
            {TABS.map(tab => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={clsx(
                  'flex items-center gap-2 px-5 py-3 text-sm font-medium whitespace-nowrap transition-colors',
                  activeTab === tab.id
                    ? 'border-b-2 border-orange-500 text-orange-600 dark:text-orange-400 bg-orange-50 dark:bg-orange-900/10'
                    : 'text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-700/50'
                )}
              >
                {tab.icon}
                {t(tab.labelKey, tab.id)}
              </button>
            ))}
          </div>

          {/* ── Tab Content ───────────────────────────────────── */}
          <div className="p-4 sm:p-6">
            {activeTab === 'pods'    && <PodControl     liveStatus={status} />}
            {activeTab === 'nodes'   && <NodeControl    liveStatus={status} />}
            {activeTab === 'chaos'   && <ChaosControl   status={status} onRefresh={fetchStatus} />}
            {activeTab === 'network' && <NetworkControl status={status} onRefresh={fetchStatus} />}
          </div>
        </div>

        {/* ── Recent Events Log ─────────────────────────────────── */}
        {status?.recent_events && status.recent_events.length > 0 && (
          <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-4 sm:p-6">
            <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-3">
              {t('events.title', 'Recent Events')}
            </h2>
            <div className="space-y-2 max-h-56 overflow-y-auto">
              {status.recent_events.map(ev => (
                <div key={ev.event_id} className="flex items-start gap-3 text-xs">
                  <span className={clsx('mt-0.5 w-2 h-2 rounded-full flex-shrink-0', {
                    'bg-green-500': ev.status === 'success',
                    'bg-red-500':   ev.status === 'failed',
                    'bg-yellow-500':ev.status === 'pending',
                  })} />
                  <div className="min-w-0">
                    <span className="font-medium text-gray-800 dark:text-gray-200 mr-2">
                      {ev.event_type}
                    </span>
                    <span className="text-gray-500 dark:text-gray-400">{ev.target}</span>
                  </div>
                  <span className="ml-auto text-gray-400 dark:text-gray-500 flex-shrink-0">
                    {new Date(ev.timestamp).toLocaleTimeString()}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
      </main>
    </div>
  )
}

export default Dashboard
