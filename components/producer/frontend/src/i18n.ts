/**
 * i18next configuration for HAMq Producer UI.
 *
 * Supports German (de) and English (en).
 * The selected language is persisted to localStorage under the key
 * "hamq-lang" so that the user's preference survives page reloads.
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
    // Default to German; fall back to English for missing keys
    lng: localStorage.getItem('hamq-lang') || 'de',
    fallbackLng: 'en',
    interpolation: {
      // React already escapes values — no need for i18next to do it again
      escapeValue: false,
    },
  })

export default i18n
