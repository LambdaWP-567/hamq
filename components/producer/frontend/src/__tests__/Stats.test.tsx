import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import Stats from '../components/Stats'
import type { ProducerStatus, RateDataPoint } from '../types'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { changeLanguage: vi.fn(), language: 'en' },
  }),
}))

// Recharts uses ResizeObserver; provide a no-op shim for jsdom
global.ResizeObserver = class {
  observe() {}
  unobserve() {}
  disconnect() {}
}

const baseStatus: ProducerStatus = {
  producer_id: 'test-producer',
  running: true,
  frequency_hz: 42.0,
  sequence_counter: 100,
  buffered_count: 5,
  sent_count: 200,
  error_count: 0,
  kafka_connected: true,
}

const baseHistory: RateDataPoint[] = [
  { time: 1000, sent: 0, buffered: 0 },
  { time: 2000, sent: 10, buffered: 2 },
  { time: 3000, sent: 25, buffered: 1 },
]

describe('Stats', () => {
  it('renders without crashing when status is null and history is empty', () => {
    expect(() =>
      render(<Stats rateHistory={[]} status={null} />)
    ).not.toThrow()
  })

  it('shows 0 for sent count when status is null', () => {
    render(<Stats rateHistory={[]} status={null} />)
    // The tile shows "0" for both sent and buffered
    const zeros = screen.getAllByText('0')
    expect(zeros.length).toBeGreaterThanOrEqual(2)
  })

  it('displays sent_count from status', () => {
    render(<Stats rateHistory={baseHistory} status={baseStatus} />)
    expect(screen.getByText('200')).toBeInTheDocument()
  })

  it('displays buffered_count from status', () => {
    render(<Stats rateHistory={baseHistory} status={baseStatus} />)
    expect(screen.getByText('5')).toBeInTheDocument()
  })

  it('shows Kafka connected status', () => {
    render(<Stats rateHistory={baseHistory} status={baseStatus} />)
    expect(screen.getByText('status.connected')).toBeInTheDocument()
  })

  it('shows Kafka disconnected status', () => {
    render(<Stats rateHistory={baseHistory} status={{ ...baseStatus, kafka_connected: false }} />)
    expect(screen.getByText('status.disconnected')).toBeInTheDocument()
  })

  it('shows frequency when status has frequency_hz', () => {
    render(<Stats rateHistory={baseHistory} status={baseStatus} />)
    expect(screen.getByText(/42\.0 Hz/)).toBeInTheDocument()
  })

  it('does not crash when status has missing fields (old API shape)', () => {
    const partial = { success: true } as unknown as ProducerStatus
    expect(() =>
      render(<Stats rateHistory={[]} status={partial} />)
    ).not.toThrow()
  })

  it('renders chart titles', () => {
    render(<Stats rateHistory={baseHistory} status={baseStatus} />)
    expect(screen.getByText('Messages / second')).toBeInTheDocument()
    expect(screen.getByText('Buffer size')).toBeInTheDocument()
  })
})
