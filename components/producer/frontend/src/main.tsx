/**
 * main.tsx — React 18 entry point for the HAMq Producer UI.
 *
 * Initialises i18n before mounting so that the first render already has
 * translated strings available (avoids a flash of untranslated content).
 */

import React from 'react'
import { createRoot } from 'react-dom/client'

// Initialise i18next — must be imported before App so translations are ready
import './i18n'
import './index.css'
import App from './App'

const container = document.getElementById('root')
if (!container) {
  throw new Error('Root element #root not found. Check index.html.')
}

createRoot(container).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
)
