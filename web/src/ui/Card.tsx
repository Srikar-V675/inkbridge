import type { ReactNode } from 'react'
import './Card.css'

export function Card({ children, className }: { children?: ReactNode; className?: string }) {
  const cls = ['ink-card', className].filter(Boolean).join(' ')
  return <div className={cls}>{children}</div>
}
