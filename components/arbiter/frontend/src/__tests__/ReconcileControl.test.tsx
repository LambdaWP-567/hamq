import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import ReconcileControl from '../components/ReconcileControl'
import type { ArbiterStatus } from '../types'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { changeLanguage: vi.fn(), language: 'de' },
  }),
}))

const mockPost = vi.fn()
vi.mock('../hooks/useApi', () => ({
  useApi: () => ({
    get: vi.fn(),
    post: mockPost,
  }),
}))

const baseStatus: ArbiterStatus = {
  arbiter_id: 'test-arbiter',
  running: false,
  last_reconcile_at: null,
  last_loss_rate: null,
  producers_monitored: 1,
  total_audits: 0,
}

const defaultProps = {
  token: 'tok',
  status: baseStatus,
  onStatusChange: vi.fn(),
  onReportReceived: vi.fn(),
  onToast: vi.fn(),
}

describe('ReconcileControl', () => {
  it('renders without crash', () => {
    expect(() => render(<ReconcileControl {...defaultProps} />)).not.toThrow()
  })

  it('shows controls.title via i18n (not hardcoded English)', () => {
    render(<ReconcileControl {...defaultProps} />)
    expect(screen.getByText('controls.title')).toBeInTheDocument()
  })

  it('shows reconcile_now button', () => {
    render(<ReconcileControl {...defaultProps} />)
    expect(screen.getByText('controls.reconcile_now')).toBeInTheDocument()
  })

  it('shows start button when not running', () => {
    render(<ReconcileControl {...defaultProps} />)
    expect(screen.getByText('controls.start')).toBeInTheDocument()
  })

  it('shows stop button when running', () => {
    render(<ReconcileControl {...defaultProps} status={{ ...baseStatus, running: true }} />)
    expect(screen.getByText('controls.stop')).toBeInTheDocument()
  })

  it('shows interval label via i18n', () => {
    render(<ReconcileControl {...defaultProps} />)
    expect(screen.getByText('controls.interval_label')).toBeInTheDocument()
  })

  it('shows monitoring info when status has producers', () => {
    render(<ReconcileControl {...defaultProps} status={{ ...baseStatus, producers_monitored: 2 }} />)
    expect(screen.getByText('controls.monitoring_label')).toBeInTheDocument()
  })
})
