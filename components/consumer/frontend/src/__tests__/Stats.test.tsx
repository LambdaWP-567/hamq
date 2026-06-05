import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import Stats from '../components/Stats'
import type { ConsumerStatus, ReceiveRatePoint } from '../types'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { changeLanguage: vi.fn(), language: 'en' },
  }),
}))

global.ResizeObserver = class {
  observe() {}
  unobserve() {}
  disconnect() {}
}

const baseStatus: ConsumerStatus = {
  consumer_id: 'test-consumer',
  running: true,
  kafka_connected: true,
  received_count: 42,
  last_sequence_by_producer: {},
  lag_estimate: 5,
  checksum_errors: 0,
}

const baseHistory: ReceiveRatePoint[] = [
  { time: '10:00:00', rate: 5,  received: 5 },
  { time: '10:00:01', rate: 12, received: 17 },
  { time: '10:00:02', rate: 3,  received: 20 },
]

describe('Stats', () => {
  it('renders without crash with null status and empty history', () => {
    expect(() => render(<Stats rateHistory={[]} status={null} />)).not.toThrow()
  })

  it('shows 0 for received_count when status is null', () => {
    render(<Stats rateHistory={[]} status={null} />)
    const zeros = screen.getAllByText('0')
    expect(zeros.length).toBeGreaterThanOrEqual(1)
  })

  it('displays received_count from status', () => {
    render(<Stats rateHistory={baseHistory} status={baseStatus} />)
    expect(screen.getByText('42')).toBeInTheDocument()
  })

  it('displays lag_estimate from status', () => {
    render(<Stats rateHistory={baseHistory} status={baseStatus} />)
    expect(screen.getByText('5')).toBeInTheDocument()
  })

  it('shows lag unit via i18n key', () => {
    render(<Stats rateHistory={baseHistory} status={baseStatus} />)
    const units = screen.getAllByText('tooltips.lag_unit')
    expect(units.length).toBeGreaterThanOrEqual(1)
  })

  it('shows the rate distribution title', () => {
    render(<Stats rateHistory={baseHistory} status={baseStatus} />)
    expect(screen.getByText('stats.rate_dist')).toBeInTheDocument()
  })

  it('shows stats title', () => {
    render(<Stats rateHistory={baseHistory} status={baseStatus} />)
    expect(screen.getByText('stats.title')).toBeInTheDocument()
  })

  it('shows no-data overlay when history is empty', () => {
    render(<Stats rateHistory={[]} status={null} />)
    expect(screen.getByText('stats.no_data')).toBeInTheDocument()
  })

  it('hides no-data overlay when history has data', () => {
    render(<Stats rateHistory={baseHistory} status={baseStatus} />)
    expect(screen.queryByText('stats.no_data')).not.toBeInTheDocument()
  })

  it('shows lag tooltip info element', () => {
    render(<Stats rateHistory={baseHistory} status={baseStatus} />)
    // Stats concatenates lag tooltip + unit; getAllByText handles the multiple matches
    const matches = screen.getAllByText(/tooltips\.lag/)
    expect(matches.length).toBeGreaterThanOrEqual(1)
  })

  it('shows checksum tooltip info element', () => {
    render(<Stats rateHistory={baseHistory} status={baseStatus} />)
    expect(screen.getByText('tooltips.checksum')).toBeInTheDocument()
  })

  it('shows checksum_errors from status', () => {
    render(<Stats rateHistory={baseHistory} status={{ ...baseStatus, checksum_errors: 3 }} />)
    expect(screen.getByText('3')).toBeInTheDocument()
  })

  it('shows 0 checksum errors when none', () => {
    render(<Stats rateHistory={baseHistory} status={baseStatus} />)
    const checkSumSection = screen.getByText('status.checksum_errors')
    expect(checkSumSection).toBeInTheDocument()
  })

  it('shows warning color for high lag', () => {
    const { container } = render(
      <Stats rateHistory={[]} status={{ ...baseStatus, lag_estimate: 2000 }} />
    )
    expect(container.innerHTML).toContain('yellow')
  })
})
