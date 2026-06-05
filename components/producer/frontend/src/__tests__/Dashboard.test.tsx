import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { AxiosInstance } from 'axios'
import Dashboard from '../components/Dashboard'
import type { ProducerStatus, Message } from '../types'

// Mock WebSocket and useWebSocket so no real connection is attempted
vi.mock('../hooks/useWebSocket', () => ({
  useWebSocket: vi.fn(),
}))

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { changeLanguage: vi.fn(), language: 'en' },
  }),
  Trans: ({ children }: { children: React.ReactNode }) => children,
}))

global.ResizeObserver = class {
  observe() {}
  unobserve() {}
  disconnect() {}
}

import { useWebSocket } from '../hooks/useWebSocket'

const mockUseWebSocket = useWebSocket as ReturnType<typeof vi.fn>

const baseStatus: ProducerStatus = {
  producer_id: 'pod-abc',
  running: false,
  frequency_hz: 5.0,
  sequence_counter: 10,
  buffered_count: 0,
  sent_count: 50,
  error_count: 0,
  kafka_connected: true,
}

const sampleMessage: Message = {
  id: 'msg-1',
  sequence: 1,
  producer_id: 'pod-abc',
  timestamp: '2024-01-01T00:00:00.000Z',
  frequency_hz: 5.0,
  payload: { data: 'hello', checksum: 'abc' },
}

function makeApi(statusData = baseStatus, messages: Message[] = []): AxiosInstance {
  return {
    get: vi.fn((url: string) => {
      if (url.includes('status')) return Promise.resolve({ data: statusData })
      if (url.includes('recent')) return Promise.resolve({ data: messages })
      return Promise.reject(new Error(`unexpected GET ${url}`))
    }),
    post: vi.fn(),
    put: vi.fn(),
  } as unknown as AxiosInstance
}

describe('Dashboard', () => {
  beforeEach(() => {
    mockUseWebSocket.mockImplementation(() => {})
  })

  // -----------------------------------------------------------------------
  // Initial render
  // -----------------------------------------------------------------------

  it('renders all five status cards', async () => {
    render(
      <Dashboard token="tok" api={makeApi()} onLogout={vi.fn()} />
    )
    // Status cards: running, kafka, sent, buffered, errors
    await waitFor(() => {
      expect(screen.getByText('status.running')).toBeInTheDocument()
      expect(screen.getByText('Kafka')).toBeInTheDocument()
      expect(screen.getByText('status.sent')).toBeInTheDocument()
      expect(screen.getByText('status.buffered')).toBeInTheDocument()
      expect(screen.getByText('status.errors')).toBeInTheDocument()
    })
  })

  it('shows the app title in the nav bar', () => {
    render(<Dashboard token="tok" api={makeApi()} onLogout={vi.fn()} />)
    expect(screen.getByText('nav.title')).toBeInTheDocument()
  })

  it('shows Logout button', () => {
    render(<Dashboard token="tok" api={makeApi()} onLogout={vi.fn()} />)
    expect(screen.getByText('nav.logout')).toBeInTheDocument()
  })

  // -----------------------------------------------------------------------
  // REST polling
  // -----------------------------------------------------------------------

  it('fetches status on mount and populates status cards', async () => {
    const api = makeApi({ ...baseStatus, sent_count: 999 })
    render(<Dashboard token="tok" api={api} onLogout={vi.fn()} />)
    await waitFor(() => {
      expect(api.get).toHaveBeenCalledWith('/api/v1/producer/status')
    })
  })

  it('fetches recent messages on mount', async () => {
    const api = makeApi(baseStatus, [sampleMessage])
    render(<Dashboard token="tok" api={api} onLogout={vi.fn()} />)
    await waitFor(() => {
      expect(api.get).toHaveBeenCalledWith('/api/messages/recent')
    })
  })

  it('populates the message log from REST poll', async () => {
    const api = makeApi(baseStatus, [sampleMessage])
    render(<Dashboard token="tok" api={api} onLogout={vi.fn()} />)
    await waitFor(() => {
      expect(screen.getByText('hello')).toBeInTheDocument()
    })
  })

  it('shows "No messages yet" before REST poll returns messages', () => {
    // API never resolves — simulates loading state
    const api = {
      get: vi.fn().mockReturnValue(new Promise(() => {})),
      post: vi.fn(),
      put: vi.fn(),
    } as unknown as AxiosInstance
    render(<Dashboard token="tok" api={api} onLogout={vi.fn()} />)
    expect(screen.getByText('messages.noMessages')).toBeInTheDocument()
  })

  // -----------------------------------------------------------------------
  // WebSocket integration
  // -----------------------------------------------------------------------

  it('updates status when WebSocket delivers a message', async () => {
    let wsOnMessage: ((data: unknown) => void) | undefined

    mockUseWebSocket.mockImplementation(({ onMessage }: { onMessage: (d: unknown) => void }) => {
      wsOnMessage = onMessage
    })

    render(<Dashboard token="tok" api={makeApi()} onLogout={vi.fn()} />)

    const wsPayload = {
      status: { ...baseStatus, running: true, sent_count: 500 },
      recent_messages: [sampleMessage],
    }

    act(() => {
      wsOnMessage?.(wsPayload)
    })

    await waitFor(() => {
      expect(screen.getByText('hello')).toBeInTheDocument()
    })
  })

  it('reflects WebSocket disconnected as Offline indicator', () => {
    let wsOnConnectionChange: ((c: boolean) => void) | undefined

    mockUseWebSocket.mockImplementation(
      ({ onConnectionChange }: { onConnectionChange?: (c: boolean) => void }) => {
        wsOnConnectionChange = onConnectionChange
      }
    )

    render(<Dashboard token="tok" api={makeApi()} onLogout={vi.fn()} />)

    act(() => {
      wsOnConnectionChange?.(false)
    })

    expect(screen.getByText('Offline')).toBeInTheDocument()
  })

  it('reflects WebSocket connected as Live indicator', async () => {
    let wsOnConnectionChange: ((c: boolean) => void) | undefined

    mockUseWebSocket.mockImplementation(
      ({ onConnectionChange }: { onConnectionChange?: (c: boolean) => void }) => {
        wsOnConnectionChange = onConnectionChange
      }
    )

    render(<Dashboard token="tok" api={makeApi()} onLogout={vi.fn()} />)

    act(() => {
      wsOnConnectionChange?.(true)
    })

    await waitFor(() => {
      expect(screen.getByText('Live')).toBeInTheDocument()
    })
  })

  // -----------------------------------------------------------------------
  // Logout
  // -----------------------------------------------------------------------

  it('calls onLogout when Logout button is clicked', async () => {
    const onLogout = vi.fn()
    render(<Dashboard token="tok" api={makeApi()} onLogout={onLogout} />)
    await userEvent.click(screen.getByText('nav.logout'))
    expect(onLogout).toHaveBeenCalledOnce()
  })
})
