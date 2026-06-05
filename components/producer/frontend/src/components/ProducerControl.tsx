/**
 * ProducerControl.tsx — Control panel for the HAMq Producer.
 *
 * Features:
 *  - Start / Stop button
 *  - Logarithmic frequency slider (1 – 1000 msg/s)
 *  - Producer ID display (set by the pod name; read-only in Kubernetes)
 *  - Live status indicator driven by WebSocket push + local optimistic state
 */

import React, { useState, useCallback, useRef, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import type { AxiosInstance } from 'axios'
import type { ProducerStatus } from '../types'

// ---------------------------------------------------------------------------
// Helpers — logarithmic slider conversion
// ---------------------------------------------------------------------------
const LOG_MIN = 0   // slider position 0  → 1 Hz
const LOG_MAX = 100 // slider position 100 → 1000 Hz

function sliderToHz(value: number): number {
  // Map [0, 100] → [1, 1000] on a log scale
  return Math.round(Math.pow(10, (value / LOG_MAX) * 3))
}

function hzToSlider(hz: number): number {
  return (Math.log10(Math.max(1, hz)) / 3) * LOG_MAX
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------
interface ProducerControlProps {
  status: ProducerStatus | null
  token: string | null
  api: AxiosInstance
  onStatusChange: (status: ProducerStatus) => void
}

export default function ProducerControl({
  status,
  api,
  onStatusChange,
}: ProducerControlProps) {
  const { t } = useTranslation()

  // Optimistic local copy of running + frequency
  const [localRunning, setLocalRunning] = useState<boolean | null>(null)
  const [sliderValue, setSliderValue] = useState<number>(
    hzToSlider(status?.frequency_hz ?? 1)
  )
  const [pendingFrequency, setPendingFrequency] = useState<boolean>(false)
  const [actionError, setActionError] = useState<string | null>(null)

  // Debounce ref for frequency apply
  const applyTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Keep slider in sync when status changes from server
  useEffect(() => {
    if (status?.frequency_hz !== undefined) {
      setSliderValue(hzToSlider(status.frequency_hz))
    }
  }, [status?.frequency_hz])

  const isRunning = localRunning !== null ? localRunning : (status?.running ?? false)
  const currentHz = sliderToHz(sliderValue)

  // ------------------------------------------------------------------
  // Start / Stop
  // ------------------------------------------------------------------
  const handleToggle = useCallback(async () => {
    setActionError(null)
    const targetRunning = !isRunning
    setLocalRunning(targetRunning)

    try {
      const endpoint = targetRunning
        ? '/api/v1/producer/start'
        : '/api/v1/producer/stop'
      const res = await api.post<ProducerStatus>(endpoint)
      onStatusChange(res.data)
      setLocalRunning(null) // server status now authoritative
    } catch {
      setActionError(
        targetRunning
          ? 'Failed to start producer'
          : 'Failed to stop producer'
      )
      setLocalRunning(null) // revert optimistic state
    }
  }, [api, isRunning, onStatusChange])

  // ------------------------------------------------------------------
  // Frequency slider — debounced apply
  // ------------------------------------------------------------------
  const handleSliderChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const val = Number(e.target.value)
      setSliderValue(val)

      // Debounce: send request 500 ms after user stops dragging
      if (applyTimer.current) clearTimeout(applyTimer.current)
      applyTimer.current = setTimeout(async () => {
        setPendingFrequency(true)
        try {
          const hz = sliderToHz(val)
          const res = await api.put<ProducerStatus>(
            '/api/v1/producer/frequency',
            { frequency_hz: hz }
          )
          onStatusChange(res.data)
        } catch {
          setActionError('Failed to update frequency')
        } finally {
          setPendingFrequency(false)
        }
      }, 500)
    },
    [api, onStatusChange]
  )

  // Cleanup debounce on unmount
  useEffect(
    () => () => {
      if (applyTimer.current) clearTimeout(applyTimer.current)
    },
    []
  )

  // ------------------------------------------------------------------
  // Render
  // ------------------------------------------------------------------
  return (
    <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 shadow-sm p-5 space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-base font-semibold text-gray-900 dark:text-white">
          Producer Control
        </h2>
        {/* Live status badge */}
        <span
          className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium
            ${isRunning
              ? 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400'
              : 'bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300'
            }`}
        >
          <span
            className={`h-1.5 w-1.5 rounded-full ${isRunning ? 'bg-green-500' : 'bg-gray-400'}`}
          />
          {isRunning ? t('status.running') : t('status.stopped')}
        </span>
      </div>

      {/* Producer ID */}
      {status?.producer_id && (
        <div>
          <p className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-1">
            Producer ID
          </p>
          <p className="text-sm font-mono text-gray-800 dark:text-gray-200 bg-gray-50 dark:bg-gray-700 rounded-lg px-3 py-2 select-all">
            {status.producer_id}
          </p>
        </div>
      )}

      {/* Start / Stop button */}
      <button
        onClick={handleToggle}
        disabled={localRunning !== null}
        className={`w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg text-sm font-semibold
          transition-colors duration-150 disabled:opacity-60 disabled:cursor-not-allowed
          ${isRunning
            ? 'bg-red-500 hover:bg-red-600 text-white'
            : 'bg-green-500 hover:bg-green-600 text-white'
          }`}
      >
        {localRunning !== null ? (
          /* Spinner while waiting for API response */
          <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" />
        ) : (
          <svg className="h-4 w-4" fill="currentColor" viewBox="0 0 24 24">
            {isRunning ? (
              <path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z" />
            ) : (
              <path d="M8 5v14l11-7z" />
            )}
          </svg>
        )}
        {isRunning ? t('controls.stop') : t('controls.start')}
      </button>

      {/* Sequence counter */}
      {status?.sequence_counter != null && (
        <div className="flex items-center justify-between text-sm">
          <span className="text-gray-500 dark:text-gray-400">{t('status.sequence')}</span>
          <span className="font-mono font-medium text-gray-800 dark:text-gray-200">
            {status.sequence_counter.toLocaleString()}
          </span>
        </div>
      )}

      {/* Frequency slider */}
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <label
            htmlFor="freq-slider"
            className="text-sm font-medium text-gray-700 dark:text-gray-300"
          >
            {t('controls.frequency')}
          </label>
          <span className="text-sm font-mono font-semibold text-gray-900 dark:text-white tabular-nums">
            {currentHz.toLocaleString()} msg/s
            {pendingFrequency && (
              <span className="ml-2 inline-block h-3 w-3 animate-spin rounded-full border-2 border-gray-400 border-t-transparent align-middle" />
            )}
          </span>
        </div>

        <input
          id="freq-slider"
          type="range"
          min={LOG_MIN}
          max={LOG_MAX}
          step={1}
          value={sliderValue}
          onChange={handleSliderChange}
          className="w-full h-2 rounded-full accent-brand-600 cursor-pointer"
          aria-label={t('controls.frequency')}
        />

        <div className="flex justify-between text-xs text-gray-400 dark:text-gray-500 select-none">
          <span>1 msg/s</span>
          <span>10</span>
          <span>100</span>
          <span>1000 msg/s</span>
        </div>
        <p className="text-xs text-gray-400 dark:text-gray-500">{t('controls.frequencyHint')}</p>
      </div>

      {/* Error banner */}
      {actionError && (
        <div className="rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800
                        px-4 py-3 text-sm text-red-700 dark:text-red-400 flex items-start gap-2">
          <svg className="h-4 w-4 mt-0.5 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
              d="M12 9v2m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          <span>{actionError}</span>
          <button
            className="ml-auto text-red-400 hover:text-red-600"
            onClick={() => setActionError(null)}
            aria-label="Dismiss"
          >
            ×
          </button>
        </div>
      )}
    </div>
  )
}
