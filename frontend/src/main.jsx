import React from 'react'
import { createRoot } from 'react-dom/client'
import App from './App.jsx'
import DesktopFrame from './DesktopFrame.jsx'
import './index.css'

createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <DesktopFrame><App /></DesktopFrame>
  </React.StrictMode>,
)
