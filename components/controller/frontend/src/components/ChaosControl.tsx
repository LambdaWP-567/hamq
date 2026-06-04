/**
 * ChaosControl.tsx — Chaos engineering control panel.
 *
 * Allows enabling/disabling random chaos actions (pod deletion, node drain,
 * network partition) on a configurable schedule.
 * All destructive actions require explicit confirmation.
 */

import React, { useState, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { Zap, Play, Square, AlertTriangle, Clock, RefreshCw } from 'lucide-react'
import clsx from 'clsx'
import { useApi } from '../hooks/useApi'
import type { ControllerStatus, ChaosConfig, ChaosAction } from '../types'

interface Props {
  status: ControllerStatus | null
  onRefresh: () => void
}

const CHAOS_ACTIONS: { value: ChaosAction; label: string }[] = [
  { value: 'random_pod_delete',   label: 'Random Pod Deletion' },
  { value: 'node_drain',          label: 'Node Drain' },
  { value: 'network_partition',   label: 'Network Partition' },
]

const ChaosControl: React.FC<Props> = ({ status, onRefresh }) => {
  const { t } = useTranslation()
  const api = useApi()

  const chaosActive = status?.chaos_enabled ?? false

  // Local form state (current config shown in the UI)
  const [action,          setAction]          = useState<ChaosAction>('random_pod_delete')
  const [intervalSeconds, setIntervalSeconds] = useState(60)
  const [maxPods,         setMaxPods]         = useState(1)
  const [targetNs,        setTargetNs]        = useState('kafka')
  const [dryRun,          setDryRun]          = useState(false)
  const [loading,         setLoading]         = useState(false)
  const [error,           setError]           = useState<string | null>(null)
  const [confirmStop,     setConfirmStop]     = useState(false)

  const applyConfig = useCallback(async (enabled: boolean) => {
    setLoading(true)
    setError(null)
    const payload: ChaosConfig = {
      enabled,
      action,
      target_namespace: targetNs,
      dry_run: dryRun,
    }
    try {
      await api.runChaos(payload)
      onRefresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Request failed')
    } finally {
      setLoading(false)
      setConfirmStop(false)
    }
  }, [api, action, targetNs, dryRun, onRefresh])

  const runOnce = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      await api.runChaos({
        enabled: true,
        action,
        target_namespace: targetNs,
        dry_run: dryRun,
      })
      onRefresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Request failed')
    } finally {
      setLoading(false)
    }
  }, [api, action, targetNs, dryRun, onRefresh])

  return (
    <div className="space-y-6">
      {/* Status banner */}
      <div className={clsx(
        'flex items-center gap-3 p-4 rounded-xl border',
        chaosActive
          ? 'bg-orange-50 border-orange-200 dark:bg-orange-900/20 dark:border-orange-800'
          : 'bg-gray-50 border-gray-200 dark:bg-gray-700/50 dark:border-gray-600'
      )}>
        <Zap className={clsx('w-5 h-5', chaosActive ? 'text-orange-500' : 'text-gray-400')} />
        <div className="flex-1">
          <p className={clsx('font-semibold text-sm', chaosActive ? 'text-orange-700 dark:text-orange-400' : 'text-gray-600 dark:text-gray-300')}>
            {chaosActive ? t('chaos.active', 'Chaos Mode ACTIVE') : t('chaos.inactive', 'Chaos Mode Inactive')}
          </p>
          {chaosActive && (
            <p className="text-xs text-orange-600 dark:text-orange-500 mt-0.5">
              {t('chaos.warning', 'Random failures are being injected into the cluster.')}
            </p>
          )}
        </div>
        <button onClick={onRefresh} className="p-1.5 rounded text-gray-400 hover:text-gray-600 dark:hover:text-gray-200">
          <RefreshCw className="w-4 h-4" />
        </button>
      </div>

      {/* ── Configuration form ─────────────────────────────── */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        {/* Action type */}
        <div>
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
            {t('chaos.action', 'Chaos Action')}
          </label>
          <select
            value={action}
            onChange={e => setAction(e.target.value as ChaosAction)}
            className="w-full rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white px-3 py-2 text-sm focus:ring-2 focus:ring-orange-500 focus:border-transparent"
          >
            {CHAOS_ACTIONS.map(a => (
              <option key={a.value} value={a.value}>{a.label}</option>
            ))}
          </select>
        </div>

        {/* Target namespace */}
        <div>
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
            {t('chaos.targetNamespace', 'Target Namespace')}
          </label>
          <input
            type="text"
            value={targetNs}
            onChange={e => setTargetNs(e.target.value)}
            className="w-full rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white px-3 py-2 text-sm focus:ring-2 focus:ring-orange-500 focus:border-transparent"
            placeholder="kafka"
          />
        </div>

        {/* Interval slider */}
        <div>
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
            {t('chaos.interval', 'Interval')}: <span className="font-bold text-orange-500">{intervalSeconds}s</span>
          </label>
          <input
            type="range"
            min={10}
            max={3600}
            step={10}
            value={intervalSeconds}
            onChange={e => setIntervalSeconds(Number(e.target.value))}
            className="w-full accent-orange-500"
          />
          <div className="flex justify-between text-xs text-gray-400 dark:text-gray-500 mt-0.5">
            <span>10s</span><span>1h</span>
          </div>
        </div>

        {/* Max pods per round */}
        <div>
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
            {t('chaos.maxPods', 'Max Pods/Round')}: <span className="font-bold text-orange-500">{maxPods}</span>
          </label>
          <input
            type="range"
            min={1}
            max={5}
            step={1}
            value={maxPods}
            onChange={e => setMaxPods(Number(e.target.value))}
            className="w-full accent-orange-500"
          />
          <div className="flex justify-between text-xs text-gray-400 dark:text-gray-500 mt-0.5">
            <span>1</span><span>5</span>
          </div>
        </div>
      </div>

      {/* Dry run toggle */}
      <label className="flex items-center gap-3 cursor-pointer select-none">
        <div className="relative">
          <input type="checkbox" checked={dryRun} onChange={e => setDryRun(e.target.checked)} className="sr-only" />
          <div className={clsx('w-10 h-5 rounded-full transition-colors', dryRun ? 'bg-blue-500' : 'bg-gray-300 dark:bg-gray-600')} />
          <div className={clsx('absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full shadow transition-transform', dryRun && 'translate-x-5')} />
        </div>
        <span className="text-sm text-gray-700 dark:text-gray-300">
          {t('chaos.dryRun', 'Dry Run (log only, no actual changes)')}
        </span>
      </label>

      {error && (
        <div className="flex items-center gap-2 text-sm text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-3">
          <AlertTriangle className="w-4 h-4 flex-shrink-0" />
          {error}
        </div>
      )}

      {/* ── Action buttons ─────────────────────────────────── */}
      <div className="flex flex-wrap gap-3">
        {!chaosActive ? (
          <button
            onClick={() => applyConfig(true)}
            disabled={loading}
            className="flex items-center gap-2 px-4 py-2 bg-orange-500 hover:bg-orange-600 disabled:opacity-50 text-white rounded-lg text-sm font-medium transition-colors"
          >
            <Play className="w-4 h-4" />
            {loading ? t('actions.starting', 'Starting…') : t('actions.startChaos', 'Start Chaos')}
          </button>
        ) : (
          <>
            {!confirmStop ? (
              <button
                onClick={() => setConfirmStop(true)}
                className="flex items-center gap-2 px-4 py-2 bg-red-500 hover:bg-red-600 text-white rounded-lg text-sm font-medium transition-colors"
              >
                <Square className="w-4 h-4" />
                {t('actions.stopChaos', 'Stop Chaos')}
              </button>
            ) : (
              <div className="flex items-center gap-2">
                <span className="text-sm text-red-600 dark:text-red-400 font-medium">
                  {t('chaos.confirmStop', 'Are you sure?')}
                </span>
                <button
                  onClick={() => applyConfig(false)}
                  disabled={loading}
                  className="px-3 py-1.5 bg-red-500 hover:bg-red-600 disabled:opacity-50 text-white rounded-lg text-sm font-medium"
                >
                  {t('yes', 'Yes, Stop')}
                </button>
                <button
                  onClick={() => setConfirmStop(false)}
                  className="px-3 py-1.5 bg-gray-200 dark:bg-gray-700 text-gray-700 dark:text-gray-300 rounded-lg text-sm font-medium"
                >
                  {t('cancel', 'Cancel')}
                </button>
              </div>
            )}
          </>
        )}

        <button
          onClick={runOnce}
          disabled={loading}
          className="flex items-center gap-2 px-4 py-2 bg-gray-100 hover:bg-gray-200 dark:bg-gray-700 dark:hover:bg-gray-600 disabled:opacity-50 text-gray-700 dark:text-gray-200 rounded-lg text-sm font-medium transition-colors"
        >
          <Clock className="w-4 h-4" />
          {t('actions.runOnce', 'Run Once Now')}
        </button>
      </div>
    </div>
  )
}

export default ChaosControl
