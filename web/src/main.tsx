import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import Root from './app/Root.tsx'
import { configureExcalidraw } from './lib/excalidrawEnv'
import { startMeasure } from './lib/measure'

// Excalidraw reads both globals lazily (pointer move, first font load), so before the first render is early enough.
configureExcalidraw(window, import.meta.env.BASE_URL)

if (import.meta.env.DEV) {
  void import('./lib/devLog').then((m) => import('./lib/timing').then((t) => t.addTimingSink(m.devSink)))
}

startMeasure()

const root = createRoot(document.getElementById('root')!)
if (import.meta.env.DEV && new URLSearchParams(window.location.search).has('kit')) {
  // Dev-only primitives page (INK-160). The DEV constant is folded away in a production build, so the module is not bundled.
  void import('./ui/Kit.tsx').then((m) => root.render(<StrictMode><m.Kit /></StrictMode>))
} else {
  root.render(<StrictMode><Root /></StrictMode>)
}
