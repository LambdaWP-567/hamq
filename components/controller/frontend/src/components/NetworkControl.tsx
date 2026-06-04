/**
 * NetworkControl.tsx — Network partition management panel.
 *
 * Allows creating Kubernetes NetworkPolicies that isolate specific pods
 * to simulate network partitions (split-brain scenarios).
 * All policies can be listed and deleted individually.
 *
 * ⚠️  WARNING: Creating network partitions on production clusters can cause
 * data loss if Kafka loses quorum. Use with caution.
 */

import React, { useState, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { Network, Plus, Trash2, AlertTriangle, RefreshCw, Shield } from 'lucide-react'
import clsx from 'clsx'
import { useApi } from '../hooks/useApi'
import type { ControllerStatus, NetworkPolicyInfo } from '../types'

interface Props {
  status: ControllerStatus | null
  onRefresh: () => void
}

/** Preset isolation targets for quick selection */
const PRESETS = [
  { label: 'Isolate Kafka Broker 0', namespace: 'kafka', selector: { 'strimzi.io/pod-name': 'hamq-kafka-dual-role-0' } },
  { label: 'Isolate Kafka Broker 1', namespace: 'kafka', selector: { 'strimzi.io/pod-name': 'hamq-kafka-dual-role-1' } },
  { label: 'Isolate Kafka Broker 2', namespace: 'kafka', selector: { 'strimzi.io/pod-name': 'hamq-kafka-dual-role-2' } },
]

const NetworkControl: React.FC<Props> = ({ status, onRefresh }) => {
  const { t } = useTranslation()
  const api = useApi()

  const policies: NetworkPolicyInfo[] = status?.active_partitions ?? []

  const [policyName,  setPolicyName]  = useState('')
  const [targetNs,    setTargetNs]    = useState('kafka')
  const [selectorStr, setSelectorStr] = useState('{"strimzi.io/pod-name": "hamq-kafka-dual-role-0"}')
  const [loading,     setLoading]     = useState(false)
  const [deleting,    setDeleting]    = useState<string | null>(null)
  const [error,       setError]       = useState<string | null>(null)
  const [confirmIdx,  setConfirmIdx]  = useState<string | null>(null)

  const applyPreset = (preset: typeof PRESETS[0]) => {
    setPolicyName(`isolate-${preset.selector['strimzi.io/pod-name']}`)
    setTargetNs(preset.namespace)
    setSelectorStr(JSON.stringify(preset.selector, null, 0))
  }

  const createPolicy = useCallback(async () => {
    setLoading(true)
    setError(null)
    let selector: Record<string, string>
    try {
      selector = JSON.parse(selectorStr)
    } catch {
      setError(t('network.invalidJson', 'Pod selector is not valid JSON'))
      setLoading(false)
      return
    }
    try {
      await api.createNetworkPartition({
        name: policyName || `partition-${Date.now()}`,
        target_namespace: targetNs,
        pod_selector: selector,
      })
      setPolicyName('')
      onRefresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Request failed')
    } finally {
      setLoading(false)
    }
  }, [api, policyName, targetNs, selectorStr, onRefresh, t])

  const deletePolicy = useCallback(async (name: string, namespace: string) => {
    setDeleting(name)
    setError(null)
    try {
      await api.deleteNetworkPartition(name, namespace)
      onRefresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Delete failed')
    } finally {
      setDeleting(null)
      setConfirmIdx(null)
    }
  }, [api, onRefresh])

  return (
    <div className="space-y-6">
      {/* Warning banner */}
      <div className="flex items-start gap-3 p-4 bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-xl">
        <AlertTriangle className="w-5 h-5 text-amber-500 flex-shrink-0 mt-0.5" />
        <div>
          <p className="text-sm font-semibold text-amber-800 dark:text-amber-400">
            {t('network.warning.title', 'Destructive Operation')}
          </p>
          <p className="text-xs text-amber-700 dark:text-amber-500 mt-0.5">
            {t('network.warning.body',
              'Network partitions can cause Kafka quorum loss if more than one broker is isolated simultaneously. Ensure min.insync.replicas allows continued operation before proceeding.'
            )}
          </p>
        </div>
      </div>

      {/* ── Active Policies ─────────────────────────────────── */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300 flex items-center gap-2">
            <Shield className="w-4 h-4" />
            {t('network.activePolicies', 'Active Network Policies')} ({policies.length})
          </h3>
          <button onClick={onRefresh} className="p-1.5 text-gray-400 hover:text-gray-600 dark:hover:text-gray-200">
            <RefreshCw className="w-3.5 h-3.5" />
          </button>
        </div>

        {policies.length === 0 ? (
          <div className="text-center py-8 text-gray-400 dark:text-gray-500 text-sm border border-dashed border-gray-200 dark:border-gray-700 rounded-xl">
            <Network className="w-6 h-6 mx-auto mb-2 opacity-50" />
            {t('network.noPolicies', 'No active network partitions')}
          </div>
        ) : (
          <div className="space-y-2">
            {policies.map(policy => (
              <div
                key={`${policy.namespace}/${policy.name}`}
                className="flex items-center gap-3 p-3 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg"
              >
                <div className="w-2 h-2 rounded-full bg-red-500 flex-shrink-0 animate-pulse" />
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-gray-800 dark:text-gray-200 truncate">{policy.name}</p>
                  <p className="text-xs text-gray-500 dark:text-gray-400">{policy.namespace}</p>
                </div>
                {confirmIdx === policy.name ? (
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-red-600 dark:text-red-400">{t('confirm.sure', 'Sure?')}</span>
                    <button
                      onClick={() => deletePolicy(policy.name, policy.namespace)}
                      disabled={deleting === policy.name}
                      className="px-2 py-1 text-xs bg-red-500 hover:bg-red-600 disabled:opacity-50 text-white rounded"
                    >
                      {t('yes', 'Yes')}
                    </button>
                    <button
                      onClick={() => setConfirmIdx(null)}
                      className="px-2 py-1 text-xs bg-gray-200 dark:bg-gray-700 text-gray-700 dark:text-gray-300 rounded"
                    >
                      {t('cancel', 'No')}
                    </button>
                  </div>
                ) : (
                  <button
                    onClick={() => setConfirmIdx(policy.name)}
                    className="p-1.5 text-red-500 hover:text-red-700 dark:hover:text-red-400 transition-colors"
                    title={t('actions.delete', 'Remove partition')}
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* ── Create New Partition ────────────────────────────── */}
      <div className="border-t border-gray-200 dark:border-gray-700 pt-6">
        <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-4 flex items-center gap-2">
          <Plus className="w-4 h-4" />
          {t('network.create', 'Create Network Partition')}
        </h3>

        {/* Presets */}
        <div className="flex flex-wrap gap-2 mb-4">
          {PRESETS.map(p => (
            <button
              key={p.label}
              onClick={() => applyPreset(p)}
              className="px-3 py-1.5 text-xs bg-gray-100 hover:bg-gray-200 dark:bg-gray-700 dark:hover:bg-gray-600 text-gray-700 dark:text-gray-300 rounded-lg transition-colors"
            >
              {p.label}
            </button>
          ))}
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
              {t('network.policyName', 'Policy Name')}
            </label>
            <input
              type="text"
              value={policyName}
              onChange={e => setPolicyName(e.target.value)}
              placeholder="isolate-broker-0"
              className="w-full rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white px-3 py-2 text-sm focus:ring-2 focus:ring-red-500 focus:border-transparent"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
              {t('network.namespace', 'Namespace')}
            </label>
            <input
              type="text"
              value={targetNs}
              onChange={e => setTargetNs(e.target.value)}
              placeholder="kafka"
              className="w-full rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white px-3 py-2 text-sm focus:ring-2 focus:ring-red-500 focus:border-transparent"
            />
          </div>
        </div>

        <div className="mb-4">
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
            {t('network.podSelector', 'Pod Selector (JSON)')}
          </label>
          <textarea
            value={selectorStr}
            onChange={e => setSelectorStr(e.target.value)}
            rows={3}
            className="w-full rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white px-3 py-2 text-sm font-mono focus:ring-2 focus:ring-red-500 focus:border-transparent"
          />
        </div>

        {error && (
          <div className="flex items-center gap-2 text-sm text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-3 mb-4">
            <AlertTriangle className="w-4 h-4 flex-shrink-0" />
            {error}
          </div>
        )}

        <button
          onClick={createPolicy}
          disabled={loading || !targetNs}
          className={clsx(
            'flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors',
            'bg-red-500 hover:bg-red-600 disabled:opacity-50 text-white'
          )}
        >
          <Network className="w-4 h-4" />
          {loading ? t('actions.creating', 'Creating…') : t('actions.createPartition', 'Create Partition')}
        </button>
      </div>
    </div>
  )
}

export default NetworkControl
