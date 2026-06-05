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
    i18n: { changeLanguage: vi.fn(), language: 'de' },
  }),
}))

const mockGetStatus = vi.fn()
const mockStartConsumer = vi.fn()
const mockStopConsumer = vi.fn()

vi.mock('../hooks/useApi', () => ({
  useApi: () => ({
    getStatus: mockGetStatus,
    startConsumer: mockStartConsumer,
    stopConsumer: mockStopConsumer,
    getMessages: vi.fn(),
    getRecentMessages: vi.fn(),
    getMissingSequences: vi.fn(),
  }),
}))

vi.mock('../hooks/useWebSocket', () => ({
  useWebSocket: () => ({ connected: false }),
}))

const mockStatus = {
  consumer_id: 'test-consumer-id',
  running: false,
  kafka_connected: true,
  received_count: 0,
  last_sequence_by_producer: {},
  lag_estimate: 0,
  checksum_errors: 0,
}

beforeEach(() => {
  vi.clearAllMocks()
  mockGetStatus.mockResolvedValue(mockStatus)
  mockStartConsumer.mockResolvedValue(undefined)
})

describe('Dashboard', () => {
  it('renders nav title via i18n', async () => {
    render(<Dashboard token="test-token" onLogout={vi.fn()} />)
    await waitFor(() => {
      expect(screen.getByText('nav.title')).toBeInTheDocument()
    })
  })

  it('renders Consumer Control title via i18n (not hardcoded)', async () => {
    render(<Dashboard token="test-token" onLogout={vi.fn()} />)
    await waitFor(() => {
      expect(screen.getByText('controls.title')).toBeInTheDocument()
    })
  })

  it('renders LanguageSwitcher in nav', async () => {
    render(<Dashboard token="test-token" onLogout={vi.fn()} />)
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /switch language/i })).toBeInTheDocument()
    })
  })

  it('renders start/stop button', async () => {
    render(<Dashboard token="test-token" onLogout={vi.fn()} />)
    await waitFor(() => {
      expect(screen.getByText('controls.start')).toBeInTheDocument()
    })
  })

  it('auto-starts consuming when status.running is false', async () => {
    render(<Dashboard token="test-token" onLogout={vi.fn()} />)
    await waitFor(() => {
      expect(mockStartConsumer).toHaveBeenCalledTimes(1)
    })
  })

  it('does NOT auto-start when consumer is already running', async () => {
    mockGetStatus.mockResolvedValue({ ...mockStatus, running: true })
    render(<Dashboard token="test-token" onLogout={vi.fn()} />)
    await waitFor(() => {
      expect(mockGetStatus).toHaveBeenCalled()
    })
    expect(mockStartConsumer).not.toHaveBeenCalled()
  })

  it('shows Consumer Lag with tooltip i18n key', async () => {
    render(<Dashboard token="test-token" onLogout={vi.fn()} />)
    await waitFor(() => {
      // status.lag appears in both the status card and Stats tile
      expect(screen.getAllByText('status.lag').length).toBeGreaterThanOrEqual(1)
      // Exact 'tooltips.lag' is in the card; Stats uses the combined string
      expect(screen.getByText('tooltips.lag')).toBeInTheDocument()
    })
  })

  it('shows Checksum Errors with tooltip i18n key', async () => {
    render(<Dashboard token="test-token" onLogout={vi.fn()} />)
    await waitFor(() => {
      // status.checksum_errors appears in both status card and Stats section
      expect(screen.getAllByText('status.checksum_errors').length).toBeGreaterThanOrEqual(1)
      expect(screen.getAllByText('tooltips.checksum').length).toBeGreaterThanOrEqual(1)
    })
  })

  it('shows logout button', async () => {
    const onLogout = vi.fn()
    render(<Dashboard token="test-token" onLogout={onLogout} />)
    await waitFor(() => {
      expect(screen.getByText('nav.logout')).toBeInTheDocument()
    })
  })
})
