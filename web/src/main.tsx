import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './app/App.tsx'
import { startMeasure } from './lib/measure'

if (import.meta.env.DEV) {
  void import('./lib/devLog').then((m) => import('./lib/timing').then((t) => t.addTimingSink(m.devSink)))
}

startMeasure()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
