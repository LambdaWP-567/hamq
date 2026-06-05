import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import MessageLog from '../components/MessageLog'
import type { ReceivedMessage } from '../types'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { changeLanguage: vi.fn(), language: 'en' },
  }),
}))

function makeMsg(overrides: Partial<ReceivedMessage> = {}): ReceivedMessage {
  return {
    id: 'abc-123',
    sequence: 1,
    producer_id: 'prod-1',
    received_at: '2026-06-05T12:00:00.000Z',
    timestamp: '2026-06-05T12:00:00.000Z',
    frequency_hz: 1.0,
    payload_data: 'dGVzdA==',
    checksum_valid: true,
    ...overrides,
  }
}

describe('MessageLog', () => {
  it('renders without crash with empty messages', () => {
    expect(() => render(<MessageLog messages={[]} />)).not.toThrow()
  })

  it('shows empty state message when no messages', () => {
    render(<MessageLog messages={[]} />)
    expect(screen.getByText('messages.no_messages')).toBeInTheDocument()
  })

  it('shows title via i18n key', () => {
    render(<MessageLog messages={[]} />)
    expect(screen.getByText('messages.title')).toBeInTheDocument()
  })

  it('renders message rows when messages are provided', () => {
    const msgs = [makeMsg({ sequence: 7 }), makeMsg({ sequence: 8, id: 'def-456' })]
    render(<MessageLog messages={msgs} />)
    expect(screen.getByText('7')).toBeInTheDocument()
    expect(screen.getByText('8')).toBeInTheDocument()
  })

  it('shows valid badge for checksum_valid=true', () => {
    render(<MessageLog messages={[makeMsg({ checksum_valid: true })]} />)
    expect(screen.getByText('messages.valid')).toBeInTheDocument()
  })

  it('shows invalid badge for checksum_valid=false', () => {
    render(<MessageLog messages={[makeMsg({ checksum_valid: false })]} />)
    expect(screen.getByText('messages.invalid')).toBeInTheDocument()
  })

  it('displays producer_id in rows', () => {
    render(<MessageLog messages={[makeMsg({ producer_id: 'my-producer' })]} />)
    expect(screen.getByText('my-producer')).toBeInTheDocument()
  })

  it('shows message count in header', () => {
    const msgs = [makeMsg(), makeMsg({ id: 'xyz' })]
    render(<MessageLog messages={msgs} />)
    expect(screen.getByText(/2\s*\/\s*50/)).toBeInTheDocument()
  })

  it('scroll container does NOT have contain:strict (invisible-row regression)', () => {
    const { container } = render(<MessageLog messages={[makeMsg()]} />)
    const scrollEl = container.querySelector('[role="log"]')
    expect(scrollEl).not.toBeNull()
    const style = (scrollEl as HTMLElement).style.contain
    expect(style).not.toBe('strict')
  })

  it('does not crash with 60 messages (exceeds display cap gracefully)', () => {
    const msgs = Array.from({ length: 60 }, (_, i) =>
      makeMsg({ id: `id-${i}`, sequence: i + 1 })
    )
    expect(() => render(<MessageLog messages={msgs} />)).not.toThrow()
  })
})
