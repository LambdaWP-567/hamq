/**
 * main.tsx — Controller React entry point.
 * Initialises i18n before rendering so all components have translations.
 */

import React from 'react'
import ReactDOM from 'react-dom/client'
import './i18n'
import './index.css'
import App from './App'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
)
