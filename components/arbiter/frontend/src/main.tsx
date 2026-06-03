/**
 * HAMq Arbiter — React 18 entry point.
 *
 * Initialises i18n first, then mounts the application inside the #root element.
 */

import React from 'react'
import { createRoot } from 'react-dom/client'
import './i18n'
import './index.css'
import App from './App'

const rootElement = document.getElementById('root')
if (!rootElement) {
  throw new Error('Root element #root not found in the document.')
}

createRoot(rootElement).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
)
