/**
 * i18next configuration for HAMq Arbiter UI.
 *
 * Supports English (en) and German (de).
 * The selected language is persisted to localStorage under the key
 * "hamq-arbiter-lang" so that the user's preference survives page reloads.
 */

import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'

import de from './locales/de.json'
import en from './locales/en.json'

i18n
  .use(initReactI18next)
  .init({
    resources: {
      en: { translation: en },
      de: { translation: de },
    },
    // Default to English; fall back to English for missing keys
    lng: localStorage.getItem('hamq-arbiter-lang') || 'en',
    fallbackLng: 'en',
    interpolation: {
      // React already escapes values — no need for i18next to do it again
      escapeValue: false,
    },
  })

export default i18n
