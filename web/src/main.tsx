import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './app/App.tsx'
import { configureExcalidraw } from './lib/excalidrawEnv'

// Excalidraw reads both globals lazily (pointer move, first font load), so before the first render is early enough.
configureExcalidraw(window, import.meta.env.BASE_URL)

if (import.meta.env.DEV) {
  void import('./lib/devLog').then((m) => import('./lib/timing').then((t) => t.setTimingSink(m.devSink)))
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
