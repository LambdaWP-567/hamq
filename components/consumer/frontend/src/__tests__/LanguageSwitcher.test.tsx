import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

const mockChangeLanguage = vi.fn()
let mockLanguage = 'de'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: {
      changeLanguage: (lang: string) => {
        mockLanguage = lang
        mockChangeLanguage(lang)
      },
      language: mockLanguage,
    },
  }),
}))

import LanguageSwitcher from '../components/LanguageSwitcher'

describe('LanguageSwitcher', () => {
  it('renders without crash', () => {
    expect(() => render(<LanguageSwitcher />)).not.toThrow()
  })

  it('shows DE label when language is de', () => {
    render(<LanguageSwitcher />)
    expect(screen.getByText('DE')).toBeInTheDocument()
  })

  it('calls changeLanguage on click', () => {
    render(<LanguageSwitcher />)
    fireEvent.click(screen.getByRole('button'))
    expect(mockChangeLanguage).toHaveBeenCalled()
  })

  it('has accessible aria-label', () => {
    render(<LanguageSwitcher />)
    expect(screen.getByRole('button', { name: /switch language/i })).toBeInTheDocument()
  })
})
