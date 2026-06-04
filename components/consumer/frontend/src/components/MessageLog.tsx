/**
 * MessageLog.tsx — Live scrolling log of received HAMq messages.
 *
 * Features:
 *  - Color-coded rows: valid checksum (green), invalid (red)
 *  - Auto-scroll to bottom with user-scroll detection
 *  - Shows sequence, producer ID, received timestamp, and checksum status
 *  - Virtual list performance via CSS contain + fixed max-height
 */

import React, { useEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import type { ReceivedMessage } from '../types'

const MAX_DISPLAY = 100

function formatTimestamp(iso: string): string {
  try {
    return new Date(iso).toLocaleTimeString('en-GB', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    })
  } catch {
    return iso
  }
}

interface MessageLogProps {
  messages: ReceivedMessage[]
}

export default function MessageLog({ messages }: MessageLogProps) {
  const { t } = useTranslation()
  const bottomRef = useRef<HTMLDivElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const autoScrollRef = useRef<boolean>(true)

  const handleScroll = () => {
    const el = containerRef.current
    if (!el) return
    const distFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight
    autoScrollRef.current = distFromBottom < 40
  }

  useEffect(() => {
    if (autoScrollRef.current) {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
    }
  }, [messages])

  const displayed = messages.slice(-MAX_DISPLAY)

  return (
    <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 shadow-sm">
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-3 border-b border-gray-100 dark:border-gray-700">
        <h2 className="text-base font-semibold text-gray-900 dark:text-white">
          {t('messages.title')}
        </h2>
        <span className="text-xs text-gray-400 dark:text-gray-500 tabular-nums">
          {displayed.length} / {MAX_DISPLAY}
        </span>
      </div>

      {/* Column headers */}
      <div className="hidden sm:grid grid-cols-12 gap-2 px-5 py-2
                      bg-gray-50 dark:bg-gray-700/50
                      text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide
                      border-b border-gray-100 dark:border-gray-700 select-none">
        <div className="col-span-1">{t('messages.sequence')}</div>
        <div className="col-span-2">{t('messages.producer')}</div>
        <div className="col-span-4">{t('messages.received_at')}</div>
        <div className="col-span-2 text-right">{t('messages.frequency')} Hz</div>
        <div className="col-span-2 text-center">{t('messages.checksum')}</div>
        <div className="col-span-1">ID</div>
      </div>

      {/* Scrollable rows */}
      <div
        ref={containerRef}
        onScroll={handleScroll}
        className="overflow-y-auto"
        style={{ maxHeight: '420px', contain: 'strict' }}
        aria-label="Consumer message log"
        role="log"
        aria-live="polite"
      >
        {displayed.length === 0 ? (
          <div className="flex items-center justify-center h-32 text-sm text-gray-400 dark:text-gray-500">
            {t('messages.no_messages')}
          </div>
        ) : (
          displayed.map((msg) => (
            <div
              key={msg.id}
              className={`grid grid-cols-12 gap-2 px-5 py-2 border-b text-sm font-mono
                          hover:bg-gray-50 dark:hover:bg-gray-700/40 transition-colors duration-75
                          ${msg.checksum_valid
                            ? 'border-green-50 dark:border-green-900/20'
                            : 'border-red-100 dark:border-red-900/30 bg-red-50/30 dark:bg-red-900/10'
                          }`}
            >
              {/* Sequence with status dot */}
              <div className="col-span-1 flex items-center gap-1.5 min-w-0">
                <span
                  className={`h-2 w-2 rounded-full flex-shrink-0 ${
                    msg.checksum_valid ? 'bg-green-400' : 'bg-red-400'
                  }`}
                />
                <span className="tabular-nums text-gray-700 dark:text-gray-300 truncate">
                  {msg.sequence.toLocaleString()}
                </span>
              </div>

              {/* Producer ID */}
              <div
                className="col-span-2 text-gray-500 dark:text-gray-400 truncate"
                title={msg.producer_id}
              >
                {msg.producer_id}
              </div>

              {/* Received at */}
              <div className="col-span-4 text-gray-500 dark:text-gray-400 truncate">
                {formatTimestamp(msg.received_at)}
              </div>

              {/* Frequency */}
              <div className="col-span-2 text-right text-gray-600 dark:text-gray-300 tabular-nums">
                {msg.frequency_hz.toFixed(1)}
              </div>

              {/* Checksum badge */}
              <div className="col-span-2 flex items-center justify-center">
                <span
                  className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${
                    msg.checksum_valid
                      ? 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400'
                      : 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400'
                  }`}
                >
                  {msg.checksum_valid ? t('messages.valid') : t('messages.invalid')}
                </span>
              </div>

              {/* Short ID */}
              <div
                className="col-span-1 text-gray-400 dark:text-gray-500 truncate"
                title={msg.id}
              >
                {msg.id.slice(0, 6)}
              </div>
            </div>
          ))
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  )
}
