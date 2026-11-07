import type { ReactNode } from 'react'
import './Badge.css'

/** The "Draft" badge on agent work waiting for a decision. */
export function Badge({ children = 'Draft' }: { children?: ReactNode }) {
  return <span className="ink-badge">{children}</span>
}

/** Outline around the ink a thread is about (INK-134). The agent colour stays in Badge.css. */
export function GlowBox({ rect }: { rect: { left: number; top: number; width: number; height: number } }) {
  return <div className="ink-glow" style={rect} aria-hidden />
}

/** The small dot on the draft tray. */
export function DraftDot() {
  return <span className="ink-badge-dot" aria-hidden />
}
