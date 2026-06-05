import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import LoginPage from '../components/LoginPage'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { changeLanguage: vi.fn(), language: 'en' },
  }),
}))

// LanguageSwitcher uses useTranslation too; its render is mocked via the above.

function renderLogin(onLogin = vi.fn()) {
  return render(
    <MemoryRouter>
      <LoginPage onLogin={onLogin} />
    </MemoryRouter>
  )
}

describe('LoginPage', () => {
  it('renders username and password fields', () => {
    renderLogin()
    expect(screen.getByLabelText('login.username')).toBeInTheDocument()
    expect(screen.getByLabelText('login.password')).toBeInTheDocument()
  })

  it('renders the sign-in button', () => {
    renderLogin()
    expect(screen.getByRole('button', { name: 'login.submit' })).toBeInTheDocument()
  })

  it('calls onLogin with username and password on submit', async () => {
    const onLogin = vi.fn().mockResolvedValue(true)
    renderLogin(onLogin)

    await userEvent.type(screen.getByLabelText('login.username'), 'admin')
    await userEvent.type(screen.getByLabelText('login.password'), 'admin')
    await userEvent.click(screen.getByRole('button', { name: 'login.submit' }))

    await waitFor(() => {
      expect(onLogin).toHaveBeenCalledWith('admin', 'admin')
    })
  })

  it('shows error message when onLogin returns false', async () => {
    const onLogin = vi.fn().mockResolvedValue(false)
    renderLogin(onLogin)

    await userEvent.type(screen.getByLabelText('login.username'), 'bad')
    await userEvent.type(screen.getByLabelText('login.password'), 'wrong')
    await userEvent.click(screen.getByRole('button', { name: 'login.submit' }))

    await waitFor(() => {
      expect(screen.getByText('login.error')).toBeInTheDocument()
    })
  })

  it('shows error message when onLogin throws', async () => {
    const onLogin = vi.fn().mockRejectedValue(new Error('network'))
    renderLogin(onLogin)

    await userEvent.type(screen.getByLabelText('login.username'), 'admin')
    await userEvent.type(screen.getByLabelText('login.password'), 'admin')
    await userEvent.click(screen.getByRole('button', { name: 'login.submit' }))

    await waitFor(() => {
      expect(screen.getByText('login.error')).toBeInTheDocument()
    })
  })

  it('disables the form while login is in progress', async () => {
    let resolve: (v: boolean) => void = () => {}
    const onLogin = vi.fn().mockReturnValue(new Promise<boolean>((r) => { resolve = r }))
    renderLogin(onLogin)

    await userEvent.type(screen.getByLabelText('login.username'), 'admin')
    await userEvent.type(screen.getByLabelText('login.password'), 'admin')
    await userEvent.click(screen.getByRole('button', { name: 'login.submit' }))

    // While pending, fields and button should be disabled
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'login.submit' })).toBeDisabled()
    })
    expect(screen.getByLabelText('login.username')).toBeDisabled()
    expect(screen.getByLabelText('login.password')).toBeDisabled()

    // Clean up — resolve the dangling promise
    resolve(true)
  })

  it('clears the error on a new submission attempt', async () => {
    const onLogin = vi.fn()
      .mockResolvedValueOnce(false)
      .mockResolvedValueOnce(true)
    renderLogin(onLogin)

    await userEvent.type(screen.getByLabelText('login.username'), 'bad')
    await userEvent.type(screen.getByLabelText('login.password'), 'wrong')
    await userEvent.click(screen.getByRole('button', { name: 'login.submit' }))
    await waitFor(() => screen.getByText('login.error'))

    // Clear the fields and try again
    await userEvent.clear(screen.getByLabelText('login.username'))
    await userEvent.clear(screen.getByLabelText('login.password'))
    await userEvent.type(screen.getByLabelText('login.username'), 'admin')
    await userEvent.type(screen.getByLabelText('login.password'), 'admin')
    await userEvent.click(screen.getByRole('button', { name: 'login.submit' }))

    await waitFor(() => {
      expect(screen.queryByText('login.error')).not.toBeInTheDocument()
    })
  })

  it('does not call onLogin when fields are empty (HTML required)', async () => {
    const onLogin = vi.fn()
    renderLogin(onLogin)
    // Click without filling in fields — browser validation prevents submission
    await userEvent.click(screen.getByRole('button', { name: 'login.submit' }))
    expect(onLogin).not.toHaveBeenCalled()
  })
})
