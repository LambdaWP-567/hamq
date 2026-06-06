import React from 'react'
import { useTranslation } from 'react-i18next'

export default function LanguageSwitcher() {
  const { i18n } = useTranslation()
  const lang = i18n.language.startsWith('de') ? 'de' : 'en'
  const toggle = () => {
    const next = lang === 'de' ? 'en' : 'de'
    i18n.changeLanguage(next)
    localStorage.setItem('hamq-lang', next)
  }
  return (
    <button
      onClick={toggle}
      className="flex items-center gap-1 text-sm font-medium px-2.5 py-1.5 rounded-lg
                 text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700
                 transition-colors"
    >
      <span>{lang === 'de' ? '🇩🇪' : '🇬🇧'}</span>
      <span>{lang === 'de' ? 'DE' : 'EN'}</span>
    </button>
  )
}
