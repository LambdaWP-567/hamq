/**
 * GapReport — Table of detected message-loss audit records.
 *
 * Fetches GET /api/audits and displays each audit as a row with:
 *   producer_id | sent | received | missing (gap_size) | loss_rate | timestamp | status
 *
 * Features:
 * - Sortable columns (click header to toggle asc/desc)
 * - Color coding: green OK, yellow warning, red critical
 * - Expandable row to show individual missing sequence numbers
 * - Export to CSV
 * - Pagination (25 rows per page)
 */

import React, { useState, useEffect, useCallback, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { useApi } from '../hooks/useApi'
import type { AuditSummary, AuditResult } from '../types'

const PAGE_SIZE = 25

interface GapReportProps {
  token: string | null
}

type SortKey = keyof Pick<
  AuditSummary,
  'producer_id' | 'sent_count' | 'received_count' | 'loss_rate' | 'timestamp' | 'status'
>

interface SortState {
  key: SortKey
  dir: 'asc' | 'desc'
}

// Status badge colours
const statusBadge: Record<string, string> = {
  ok:       'bg-green-100 text-green-700',
  warning:  'bg-yellow-100 text-yellow-700',
  critical: 'bg-red-100 text-red-700',
}

export default function GapReport({ token }: GapReportProps) {
  const { t } = useTranslation()
  const api = useApi(token)

  const [audits, setAudits] = useState<AuditSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [sort, setSort] = useState<SortState>({ key: 'timestamp', dir: 'desc' })
  const [page, setPage] = useState(1)
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [expandedData, setExpandedData] = useState<AuditResult | null>(null)
  const [expandLoading, setExpandLoading] = useState(false)

  // ---------------------------------------------------------------------------
  // Fetch
  // ---------------------------------------------------------------------------

  const fetchAudits = useCallback(async () => {
    setError(null)
    try {
      const res = await api.get<AuditSummary[]>('/api/audits?limit=500')
      setAudits(res.data)
    } catch {
      setError(t('errors.fetch_failed'))
    } finally {
      setLoading(false)
    }
  }, [api, t])

  useEffect(() => {
    fetchAudits()
    const interval = setInterval(fetchAudits, 15000)
    return () => clearInterval(interval)
  }, [fetchAudits])

  // ---------------------------------------------------------------------------
  // Sorting
  // ---------------------------------------------------------------------------

  const handleSort = (key: SortKey) => {
    setSort((prev) =>
      prev.key === key
        ? { key, dir: prev.dir === 'asc' ? 'desc' : 'asc' }
        : { key, dir: 'desc' }
    )
    setPage(1)
  }

  const sortedAudits = useMemo(() => {
    return [...audits].sort((a, b) => {
      const valA = a[sort.key]
      const valB = b[sort.key]
      if (valA === undefined || valB === undefined) return 0
      const cmp =
        typeof valA === 'number' && typeof valB === 'number'
          ? valA - valB
          : String(valA).localeCompare(String(valB))
      return sort.dir === 'asc' ? cmp : -cmp
    })
  }, [audits, sort])

  const totalPages = Math.max(1, Math.ceil(sortedAudits.length / PAGE_SIZE))
  const pageAudits = sortedAudits.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE)

  // ---------------------------------------------------------------------------
  // Expand row to load missing sequences
  // ---------------------------------------------------------------------------

  const handleExpand = useCallback(
    async (auditId: string) => {
      if (expandedId === auditId) {
        setExpandedId(null)
        setExpandedData(null)
        return
      }
      setExpandedId(auditId)
      setExpandedData(null)
      setExpandLoading(true)
      try {
        const res = await api.get<AuditResult>(`/api/audits/${auditId}`)
        setExpandedData(res.data)
      } catch {
        setExpandedData(null)
      } finally {
        setExpandLoading(false)
      }
    },
    [api, expandedId]
  )

  // ---------------------------------------------------------------------------
  // CSV export
  // ---------------------------------------------------------------------------

  const handleExportCsv = useCallback(() => {
    const header = ['audit_id', 'producer_id', 'sent_count', 'received_count', 'loss_rate', 'timestamp', 'status']
    const rows = sortedAudits.map((a) =>
      [
        a.audit_id,
        a.producer_id,
        a.sent_count,
        a.received_count,
        (a.loss_rate * 100).toFixed(4),
        a.timestamp,
        a.status,
      ].join(',')
    )
    const csv = [header.join(','), ...rows].join('\n')
    const blob = new Blob([csv], { type: 'text/csv' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `hamq-audits-${new Date().toISOString().slice(0, 10)}.csv`
    link.click()
    URL.revokeObjectURL(url)
  }, [sortedAudits])

  // ---------------------------------------------------------------------------
  // Sort indicator
  // ---------------------------------------------------------------------------

  const SortIcon = ({ col }: { col: SortKey }) => {
    if (sort.key !== col) return <span className="ml-1 text-gray-300">↕</span>
    return <span className="ml-1">{sort.dir === 'asc' ? '↑' : '↓'}</span>
  }

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  if (loading) {
    return (
      <div className="card flex items-center justify-center h-40 text-gray-400 text-sm">
        <span className="inline-block h-5 w-5 animate-spin rounded-full border-2 border-brand-400 border-t-transparent mr-2" />
        {t('audit.loading')}
      </div>
    )
  }

  if (error) {
    return (
      <div className="card flex flex-col items-center justify-center h-40 gap-3">
        <p className="text-red-600 text-sm">{error}</p>
        <button onClick={fetchAudits} className="btn-secondary text-sm">
          {t('common.retry')}
        </button>
      </div>
    )
  }

  return (
    <div className="card p-0 overflow-hidden">
      {/* Header row */}
      <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100">
        <h3 className="text-sm font-semibold text-gray-700">
          {t('audit.title')}
          <span className="ml-2 inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-600">
            {audits.length}
          </span>
        </h3>
        <div className="flex items-center gap-2">
          <button onClick={fetchAudits} className="btn-secondary text-xs px-2.5 py-1.5">
            {t('audit.refresh')}
          </button>
          <button onClick={handleExportCsv} disabled={audits.length === 0} className="btn-secondary text-xs px-2.5 py-1.5">
            {t('audit.export_csv')}
          </button>
        </div>
      </div>

      {audits.length === 0 ? (
        <div className="flex items-center justify-center h-40 text-gray-400 text-sm">
          {t('audit.no_audits')}
        </div>
      ) : (
        <>
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr>
                  {(
                    [
                      { key: 'producer_id' as SortKey, label: t('audit.producer') },
                      { key: 'sent_count' as SortKey, label: t('audit.sent') },
                      { key: 'received_count' as SortKey, label: t('audit.received') },
                      { key: 'loss_rate' as SortKey, label: t('audit.missing') },
                      { key: 'timestamp' as SortKey, label: t('audit.timestamp') },
                      { key: 'status' as SortKey, label: '' },
                    ] as Array<{ key: SortKey; label: string }>
                  ).map(({ key, label }) => (
                    <th
                      key={key}
                      onClick={() => handleSort(key)}
                      className="table-header cursor-pointer select-none hover:bg-gray-100 transition-colors"
                    >
                      {label}
                      <SortIcon col={key} />
                    </th>
                  ))}
                  <th className="table-header">{t('audit.details')}</th>
                </tr>
              </thead>
              <tbody>
                {pageAudits.map((audit) => {
                  const missingCount = audit.sent_count - audit.received_count
                  const isExpanded = expandedId === audit.audit_id
                  return (
                    <React.Fragment key={audit.audit_id}>
                      <tr
                        className={`hover:bg-gray-50 transition-colors ${
                          audit.status === 'critical' ? 'bg-red-50/30' : ''
                        }`}
                      >
                        <td className="table-cell font-mono text-xs">{audit.producer_id}</td>
                        <td className="table-cell tabular-nums">{audit.sent_count.toLocaleString()}</td>
                        <td className="table-cell tabular-nums">{audit.received_count.toLocaleString()}</td>
                        <td className={`table-cell tabular-nums font-medium
                          ${missingCount === 0 ? 'text-green-600' : missingCount < 10 ? 'text-yellow-600' : 'text-red-600'}`}>
                          {missingCount.toLocaleString()}
                        </td>
                        <td className="table-cell text-xs text-gray-500">
                          {new Date(audit.timestamp).toLocaleString()}
                        </td>
                        <td className="table-cell">
                          <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium
                            ${statusBadge[audit.status] ?? 'bg-gray-100 text-gray-600'}`}>
                            {t(`status.${audit.status}` as Parameters<typeof t>[0]) || audit.status}
                          </span>
                        </td>
                        <td className="table-cell">
                          {missingCount > 0 && (
                            <button
                              onClick={() => handleExpand(audit.audit_id)}
                              className="text-xs text-brand-600 hover:text-brand-800 font-medium transition-colors"
                            >
                              {isExpanded ? t('audit.collapse') : t('audit.expand')}
                            </button>
                          )}
                        </td>
                      </tr>

                      {/* Expanded detail row */}
                      {isExpanded && (
                        <tr>
                          <td colSpan={7} className="px-5 py-3 bg-gray-50 border-b border-gray-100">
                            {expandLoading ? (
                              <span className="text-xs text-gray-400">{t('common.loading')}</span>
                            ) : expandedData ? (
                              <div>
                                <p className="text-xs font-medium text-gray-600 mb-1">
                                  {t('audit.missing_sequences')} ({expandedData.missing_sequences.length})
                                </p>
                                <p className="text-xs font-mono text-gray-700 break-all leading-relaxed">
                                  {expandedData.missing_sequences.length === 0
                                    ? t('audit.no_missing')
                                    : expandedData.missing_sequences.slice(0, 200).join(', ')
                                      + (expandedData.missing_sequences.length > 200 ? ` … +${expandedData.missing_sequences.length - 200} ${t('audit.more')}` : '')
                                  }
                                </p>
                              </div>
                            ) : null}
                          </td>
                        </tr>
                      )}
                    </React.Fragment>
                  )
                })}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="flex items-center justify-between px-5 py-3 border-t border-gray-100 bg-gray-50">
              <p className="text-xs text-gray-500">
                {((page - 1) * PAGE_SIZE) + 1}–{Math.min(page * PAGE_SIZE, sortedAudits.length)} of {sortedAudits.length}
              </p>
              <div className="flex items-center gap-1">
                <button
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  disabled={page === 1}
                  className="btn-secondary text-xs px-2.5 py-1.5 disabled:opacity-40"
                >
                  ← Prev
                </button>
                <span className="px-3 py-1.5 text-xs text-gray-600">
                  {page} / {totalPages}
                </span>
                <button
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                  disabled={page === totalPages}
                  className="btn-secondary text-xs px-2.5 py-1.5 disabled:opacity-40"
                >
                  Next →
                </button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
