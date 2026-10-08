import React from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import './fonts.css'
import './styles.css'
import App from './App'
import { ToastProvider } from './ui'

createRoot(document.getElementById('root')).render(
  <BrowserRouter basename="/navi"><ToastProvider><App /></ToastProvider></BrowserRouter>)
