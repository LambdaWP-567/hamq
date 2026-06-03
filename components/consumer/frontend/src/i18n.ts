/**
 * react-i18next initialisation for the HAMq Consumer SPA.
 *
 * Supported languages:
 *   - de  German  (primary UI language)
 *   - en  English (fallback)
 *
 * Language preference is persisted in localStorage under the key "hamq-lang".
 */

import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'

import de from './locales/de.json'
import en from './locales/en.json'

i18n
  .use(initReactI18next)
  .init({
    resources: {
      de: { translation: de },
      en: { translation: en },
    },
    // Default to German; fallback to English for any missing key.
    lng: localStorage.getItem('hamq-lang') ?? 'de',
    fallbackLng: 'en',
    interpolation: {
      // React escapes values by default — no need for i18next to escape.
      escapeValue: false,
    },
  })

export default i18n
