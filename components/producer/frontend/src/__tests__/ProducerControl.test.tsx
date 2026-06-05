import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { AxiosInstance } from 'axios'
import ProducerControl from '../components/ProducerControl'
import type { ProducerStatus } from '../types'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { changeLanguage: vi.fn(), language: 'en' },
  }),
}))

const stoppedStatus: ProducerStatus = {
  producer_id: 'test-producer',
  running: false,
  frequency_hz: 1.0,
  sequence_counter: 42,
  buffered_count: 0,
  sent_count: 100,
  error_count: 0,
  kafka_connected: true,
}

const runningStatus: ProducerStatus = {
  ...stoppedStatus,
  running: true,
  frequency_hz: 10.0,
}

function makeApi(overrides: Partial<AxiosInstance> = {}): AxiosInstance {
  return {
    post: vi.fn().mockResolvedValue({ data: runningStatus }),
    put: vi.fn().mockResolvedValue({ data: runningStatus }),
    get: vi.fn(),
    ...overrides,
  } as unknown as AxiosInstance
}

describe('ProducerControl', () => {
  let onStatusChange: ReturnType<typeof vi.fn>

  beforeEach(() => {
    onStatusChange = vi.fn()
  })

  // -----------------------------------------------------------------------
  // Rendering
  // -----------------------------------------------------------------------

  it('shows Start button when producer is stopped', () => {
    render(
      <ProducerControl
        status={stoppedStatus}
        token="tok"
        api={makeApi()}
        onStatusChange={onStatusChange}
      />
    )
    expect(screen.getByText('controls.start')).toBeInTheDocument()
  })

  it('shows Stop button when producer is running', () => {
    render(
      <ProducerControl
        status={runningStatus}
        token="tok"
        api={makeApi()}
        onStatusChange={onStatusChange}
      />
    )
    expect(screen.getByText('controls.stop')).toBeInTheDocument()
  })

  it('displays the sequence counter from status', () => {
    render(
      <ProducerControl
        status={stoppedStatus}
        token="tok"
        api={makeApi()}
        onStatusChange={onStatusChange}
      />
    )
    expect(screen.getByText('42')).toBeInTheDocument()
  })

  it('displays the producer ID from status', () => {
    render(
      <ProducerControl
        status={stoppedStatus}
        token="tok"
        api={makeApi()}
        onStatusChange={onStatusChange}
      />
    )
    expect(screen.getByText('test-producer')).toBeInTheDocument()
  })

  it('renders without crashing when status is null', () => {
    render(
      <ProducerControl
        status={null}
        token="tok"
        api={makeApi()}
        onStatusChange={onStatusChange}
      />
    )
    expect(screen.getByText('controls.start')).toBeInTheDocument()
  })

  it('does not crash when status has missing fields (old API response shape)', () => {
    const partialStatus = { success: true } as unknown as ProducerStatus
    expect(() =>
      render(
        <ProducerControl
          status={partialStatus}
          token="tok"
          api={makeApi()}
          onStatusChange={onStatusChange}
        />
      )
    ).not.toThrow()
  })

  // -----------------------------------------------------------------------
  // Start / Stop
  // -----------------------------------------------------------------------

  it('calls POST /api/v1/producer/start when Start is clicked', async () => {
    const api = makeApi()
    render(
      <ProducerControl
        status={stoppedStatus}
        token="tok"
        api={api}
        onStatusChange={onStatusChange}
      />
    )
    await userEvent.click(screen.getByText('controls.start'))
    expect(api.post).toHaveBeenCalledWith('/api/v1/producer/start')
  })

  it('calls POST /api/v1/producer/stop when Stop is clicked', async () => {
    const api = makeApi({ post: vi.fn().mockResolvedValue({ data: stoppedStatus }) })
    render(
      <ProducerControl
        status={runningStatus}
        token="tok"
        api={api}
        onStatusChange={onStatusChange}
      />
    )
    await userEvent.click(screen.getByText('controls.stop'))
    expect(api.post).toHaveBeenCalledWith('/api/v1/producer/stop')
  })

  it('calls onStatusChange with the response after start', async () => {
    const api = makeApi({ post: vi.fn().mockResolvedValue({ data: runningStatus }) })
    render(
      <ProducerControl
        status={stoppedStatus}
        token="tok"
        api={api}
        onStatusChange={onStatusChange}
      />
    )
    await userEvent.click(screen.getByText('controls.start'))
    await waitFor(() => {
      expect(onStatusChange).toHaveBeenCalledWith(runningStatus)
    })
  })

  it('shows a spinner while start/stop is pending', async () => {
    let resolve: (v: unknown) => void = () => {}
    const api = makeApi({
      post: vi.fn().mockReturnValue(new Promise((r) => { resolve = r })),
    })
    render(
      <ProducerControl
        status={stoppedStatus}
        token="tok"
        api={api}
        onStatusChange={onStatusChange}
      />
    )
    await userEvent.click(screen.getByText('controls.start'))
    // Optimistic state: localRunning=true → button shows "Stop" and is disabled
    const btn = screen.getByRole('button', { name: /controls\.stop/i })
    expect(btn).toBeDisabled()
    // Resolve the pending request
    await act(async () => resolve({ data: runningStatus }))
  })

  it('shows an error banner when start fails', async () => {
    const api = makeApi({ post: vi.fn().mockRejectedValue(new Error('network')) })
    render(
      <ProducerControl
        status={stoppedStatus}
        token="tok"
        api={api}
        onStatusChange={onStatusChange}
      />
    )
    await userEvent.click(screen.getByText('controls.start'))
    await waitFor(() => {
      expect(screen.getByText('Failed to start producer')).toBeInTheDocument()
    })
  })

  it('shows an error banner when stop fails', async () => {
    const api = makeApi({ post: vi.fn().mockRejectedValue(new Error('network')) })
    render(
      <ProducerControl
        status={runningStatus}
        token="tok"
        api={api}
        onStatusChange={onStatusChange}
      />
    )
    await userEvent.click(screen.getByText('controls.stop'))
    await waitFor(() => {
      expect(screen.getByText('Failed to stop producer')).toBeInTheDocument()
    })
  })

  it('dismisses the error banner when × is clicked', async () => {
    const api = makeApi({ post: vi.fn().mockRejectedValue(new Error('network')) })
    render(
      <ProducerControl
        status={stoppedStatus}
        token="tok"
        api={api}
        onStatusChange={onStatusChange}
      />
    )
    await userEvent.click(screen.getByText('controls.start'))
    await waitFor(() => screen.getByText('Failed to start producer'))
    await userEvent.click(screen.getByLabelText('Dismiss'))
    expect(screen.queryByText('Failed to start producer')).not.toBeInTheDocument()
  })

  // -----------------------------------------------------------------------
  // Frequency slider
  // -----------------------------------------------------------------------

  it('calls PUT /api/v1/producer/frequency after debounce', async () => {
    vi.useFakeTimers()
    const api = makeApi()
    render(
      <ProducerControl
        status={stoppedStatus}
        token="tok"
        api={api}
        onStatusChange={onStatusChange}
      />
    )
    const slider = screen.getByRole('slider')
    fireEvent.change(slider, { target: { value: '50' } })

    // Should not have fired yet
    expect(api.put).not.toHaveBeenCalled()

    // Advance past the 500 ms debounce and flush all async callbacks
    await act(async () => { await vi.runAllTimersAsync() })

    expect(api.put).toHaveBeenCalledWith(
      '/api/v1/producer/frequency',
      { frequency_hz: 32 } // sliderToHz(50) = round(10^1.5) = 32
    )
    vi.useRealTimers()
  })

  it('does not call frequency API before debounce elapses', () => {
    vi.useFakeTimers()
    const api = makeApi()
    render(
      <ProducerControl
        status={stoppedStatus}
        token="tok"
        api={api}
        onStatusChange={onStatusChange}
      />
    )
    const slider = screen.getByRole('slider')
    fireEvent.change(slider, { target: { value: '30' } })
    fireEvent.change(slider, { target: { value: '50' } })
    fireEvent.change(slider, { target: { value: '70' } })

    // All still within the debounce window
    act(() => { vi.advanceTimersByTime(300) })
    expect(api.put).not.toHaveBeenCalled()

    vi.useRealTimers()
  })

  it('shows Failed to update frequency error on slider API failure', async () => {
    vi.useFakeTimers()
    const api = makeApi({ put: vi.fn().mockRejectedValue(new Error('fail')) })
    render(
      <ProducerControl
        status={stoppedStatus}
        token="tok"
        api={api}
        onStatusChange={onStatusChange}
      />
    )
    const slider = screen.getByRole('slider')
    fireEvent.change(slider, { target: { value: '50' } })

    await act(async () => { await vi.runAllTimersAsync() })

    expect(screen.getByText('Failed to update frequency')).toBeInTheDocument()
    vi.useRealTimers()
  })

  it('updates the frequency label display when slider moves', () => {
    render(
      <ProducerControl
        status={stoppedStatus}
        token="tok"
        api={makeApi()}
        onStatusChange={onStatusChange}
      />
    )
    const slider = screen.getByRole('slider')
    fireEvent.change(slider, { target: { value: '100' } })
    // sliderToHz(100) = 1000, formatted with locale thousands separator (1,000 or 1.000)
    expect(screen.getByText(/1[,.]\d{3} msg\/s/)).toBeInTheDocument()
  })

  it('syncs slider position when status.frequency_hz changes', () => {
    const { rerender } = render(
      <ProducerControl
        status={stoppedStatus}
        token="tok"
        api={makeApi()}
        onStatusChange={onStatusChange}
      />
    )
    rerender(
      <ProducerControl
        status={{ ...stoppedStatus, frequency_hz: 1000 }}
        token="tok"
        api={makeApi()}
        onStatusChange={onStatusChange}
      />
    )
    const slider = screen.getByRole('slider') as HTMLInputElement
    expect(Number(slider.value)).toBe(100) // hzToSlider(1000) = 100
  })
})
