import type { ReactNode } from 'react'
import './Badge.css'

/** The "Draft" badge on agent work waiting for a decision. */
export function Badge({ children = 'Draft' }: { children?: ReactNode }) {
  return <span className="ink-badge">{children}</span>
}
