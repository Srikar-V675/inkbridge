import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './app/App.tsx'

if (import.meta.env.DEV) {
  void import('./lib/devLog').then((m) => import('./lib/timing').then((t) => t.setTimingSink(m.devSink)))
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
