import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import Dashboard from '../components/Dashboard'

global.ResizeObserver = class {
  observe() {}
  unobserve() {}
  disconnect() {}
}

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: {
      changeLanguage: vi.fn(),
      language: 'de',
    },
  }),
}))

const mockGet = vi.fn()
const mockPost = vi.fn()
// Stable object reference — prevents useCallback deps from changing every render
const stableApi = { get: mockGet, post: mockPost }

vi.mock('../hooks/useApi', () => ({
  useApi: () => stableApi,
}))

vi.mock('../hooks/useWebSocket', () => ({
  // Do NOT call onConnectionChange synchronously — that causes infinite re-renders
  useWebSocket: () => {},
}))

vi.mock('../components/GapReport', () => ({
  default: () => <div data-testid="gap-report">GapReport</div>,
}))
vi.mock('../components/Stats', () => ({
  default: () => <div data-testid="stats">Stats</div>,
}))

const mockStatus = {
  arbiter_id: 'arb-1',
  running: true,
  last_reconcile_at: '2026-06-05T10:00:00Z',
  last_loss_rate: 0.01,
  producers_monitored: 1,
  total_audits: 5,
}

const mockStats = {
  total_audits: 5,
  avg_loss_rate: 0.01,
  worst_producer: 'prod-1',
  worst_loss_rate: 0.05,
  producers_tracked: 1,
}

beforeEach(() => {
  vi.clearAllMocks()
  mockGet.mockImplementation((url: string) => {
    if (url.includes('/api/status')) return Promise.resolve({ data: mockStatus })
    if (url.includes('/api/stats')) return Promise.resolve({ data: mockStats })
    return Promise.resolve({ data: {} })
  })
})

describe('Dashboard', () => {
  it('renders nav title via i18n', async () => {
    render(<Dashboard token="tok" onLogout={vi.fn()} />)
    await waitFor(() => {
      expect(screen.getByText('nav.title')).toBeInTheDocument()
    })
  })

  it('renders summary cards with i18n keys', async () => {
    render(<Dashboard token="tok" onLogout={vi.fn()} />)
    await waitFor(() => {
      expect(screen.getByText('report.total_sent')).toBeInTheDocument()
      expect(screen.getByText('report.total_received')).toBeInTheDocument()
      expect(screen.getByText('report.total_missing')).toBeInTheDocument()
      expect(screen.getByText('report.success_rate')).toBeInTheDocument()
    })
  })

  it('renders about section with i18n keys', async () => {
    render(<Dashboard token="tok" onLogout={vi.fn()} />)
    await waitFor(() => {
      expect(screen.getByText('about.title')).toBeInTheDocument()
      expect(screen.getByText('about.body')).toBeInTheDocument()
    })
  })

  it('renders tab buttons for gaps and stats', async () => {
    render(<Dashboard token="tok" onLogout={vi.fn()} />)
    await waitFor(() => {
      expect(screen.getByText('audit.title')).toBeInTheDocument()
      expect(screen.getByText('stats.title')).toBeInTheDocument()
    })
  })

  it('shows no-report placeholder before reconcile runs', async () => {
    render(<Dashboard token="tok" onLogout={vi.fn()} />)
    await waitFor(() => {
      expect(screen.getByText('report.no_report')).toBeInTheDocument()
    })
  })

  it('shows logout button', async () => {
    render(<Dashboard token="tok" onLogout={vi.fn()} />)
    await waitFor(() => {
      expect(screen.getByTitle('Logout')).toBeInTheDocument()
    })
  })
})
