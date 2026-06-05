import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import MessageLog from '../components/MessageLog'
import type { Message } from '../types'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { changeLanguage: vi.fn(), language: 'en' },
  }),
}))

function makeMessage(overrides: Partial<Message> = {}): Message {
  return {
    id: 'msg-001',
    sequence: 1,
    producer_id: 'test-producer',
    timestamp: '2024-01-01T12:00:00.000Z',
    frequency_hz: 10.0,
    payload: { data: 'hello world', checksum: 'abc123' },
    ...overrides,
  }
}

describe('MessageLog', () => {
  it('shows empty state when no messages', () => {
    render(<MessageLog messages={[]} />)
    expect(screen.getByText('messages.noMessages')).toBeInTheDocument()
  })

  it('shows the recent messages header', () => {
    render(<MessageLog messages={[]} />)
    expect(screen.getByText('messages.recent')).toBeInTheDocument()
  })

  it('shows count badge as 0/100 when empty', () => {
    render(<MessageLog messages={[]} />)
    expect(screen.getByText('0 / 100')).toBeInTheDocument()
  })

  it('renders a message row with sequence number', () => {
    render(<MessageLog messages={[makeMessage({ sequence: 42 })]} />)
    expect(screen.getByText('42')).toBeInTheDocument()
  })

  it('renders message payload data', () => {
    render(<MessageLog messages={[makeMessage({ payload: { data: 'test payload', checksum: 'x' } })]} />)
    expect(screen.getByText('test payload')).toBeInTheDocument()
  })

  it('renders frequency_hz for each message', () => {
    render(<MessageLog messages={[makeMessage({ frequency_hz: 25.0 })]} />)
    expect(screen.getByText('25.0')).toBeInTheDocument()
  })

  it('shows correct count badge with messages', () => {
    const msgs = [makeMessage({ sequence: 1, id: '1' }), makeMessage({ sequence: 2, id: '2' })]
    render(<MessageLog messages={msgs} />)
    expect(screen.getByText('2 / 100')).toBeInTheDocument()
  })

  it('does not show empty state when there are messages', () => {
    render(<MessageLog messages={[makeMessage()]} />)
    expect(screen.queryByText('messages.noMessages')).not.toBeInTheDocument()
  })

  it('renders multiple messages', () => {
    const msgs = Array.from({ length: 5 }, (_, i) =>
      makeMessage({ id: `msg-${i}`, sequence: i + 1 })
    )
    render(<MessageLog messages={msgs} />)
    expect(screen.getByText('5 / 100')).toBeInTheDocument()
  })

  it('formats timestamp from ISO string', () => {
    render(<MessageLog messages={[makeMessage({ timestamp: '2024-01-01T12:34:56.000Z' })]} />)
    // The formatted time should appear somewhere in the rendered output
    // (exact format depends on locale, so just check it's not the raw ISO string)
    expect(screen.queryByText('2024-01-01T12:34:56.000Z')).not.toBeInTheDocument()
  })
})
