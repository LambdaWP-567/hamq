import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import GapReport from '../components/GapReport'
import type { AuditSummary } from '../types'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { changeLanguage: vi.fn(), language: 'de' },
  }),
}))

const mockGet = vi.fn()
vi.mock('../hooks/useApi', () => ({
  useApi: () => ({
    get: mockGet,
    post: vi.fn(),
  }),
}))

global.ResizeObserver = class {
  observe() {}
  unobserve() {}
  disconnect() {}
}

const mockAudit: AuditSummary = {
  audit_id: 'audit-1',
  timestamp: '2026-06-05T10:00:00Z',
  producer_id: 'prod-1',
  sent_count: 100,
  received_count: 98,
  loss_rate: 0.02,
  status: 'warning',
}

describe('GapReport', () => {
  it('renders loading state initially', () => {
    mockGet.mockReturnValue(new Promise(() => {}))
    render(<GapReport token="tok" />)
    expect(screen.getByText('audit.loading')).toBeInTheDocument()
  })

  it('shows empty state when no audits returned', async () => {
    mockGet.mockResolvedValue({ data: [] })
    render(<GapReport token="tok" />)
    await waitFor(() => {
      expect(screen.getByText('audit.no_audits')).toBeInTheDocument()
    })
  })

  it('shows audit rows when data exists', async () => {
    mockGet.mockResolvedValue({ data: [mockAudit] })
    render(<GapReport token="tok" />)
    await waitFor(() => {
      expect(screen.getByText('prod-1')).toBeInTheDocument()
    })
  })

  it('shows Refresh button via i18n key', async () => {
    mockGet.mockResolvedValue({ data: [] })
    render(<GapReport token="tok" />)
    await waitFor(() => {
      expect(screen.getByText('audit.refresh')).toBeInTheDocument()
    })
  })

  it('shows Export CSV button via i18n key', async () => {
    mockGet.mockResolvedValue({ data: [] })
    render(<GapReport token="tok" />)
    await waitFor(() => {
      expect(screen.getByText('audit.export_csv')).toBeInTheDocument()
    })
  })

  it('shows error state when fetch fails', async () => {
    mockGet.mockRejectedValue(new Error('Network error'))
    render(<GapReport token="tok" />)
    await waitFor(() => {
      expect(screen.getByText('errors.fetch_failed')).toBeInTheDocument()
    })
  })

  it('shows sent_count in audit row', async () => {
    mockGet.mockResolvedValue({ data: [mockAudit] })
    render(<GapReport token="tok" />)
    await waitFor(() => {
      expect(screen.getByText('100')).toBeInTheDocument()
    })
  })

  it('shows producer column header', async () => {
    mockGet.mockResolvedValue({ data: [mockAudit] })
    render(<GapReport token="tok" />)
    await waitFor(() => {
      expect(screen.getByText('audit.producer')).toBeInTheDocument()
    })
  })
})
