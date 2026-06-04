/**
 * LanguageSwitcher — Toggle between German and English.
 *
 * Persists the selected language to localStorage under "hamq-lang".
 */

import React from 'react'
import { useTranslation } from 'react-i18next'

export default function LanguageSwitcher() {
  const { i18n } = useTranslation()

  const currentLang = i18n.language.startsWith('de') ? 'de' : 'en'

  const toggle = () => {
    const next = currentLang === 'de' ? 'en' : 'de'
    i18n.changeLanguage(next)
    localStorage.setItem('hamq-lang', next)
  }

  return (
    <button
      onClick={toggle}
      title={currentLang === 'de' ? 'Switch to English' : 'Auf Deutsch wechseln'}
      className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium
                 bg-white/10 hover:bg-white/20 text-white border border-white/20
                 transition-colors duration-150"
      aria-label="Switch language"
    >
      {/* Flag emoji + language code */}
      {currentLang === 'de' ? (
        <>
          <span aria-hidden="true">🇩🇪</span>
          <span>DE</span>
        </>
      ) : (
        <>
          <span aria-hidden="true">🇬🇧</span>
          <span>EN</span>
        </>
      )}
    </button>
  )
}
