import type { ReactNode } from 'react'
import './Panel.css'

export function Panel({ title, children, className }: { title?: string; children?: ReactNode; className?: string }) {
  const cls = ['ink-panel', className].filter(Boolean).join(' ')
  return (
    <aside className={cls}>
      {title && <h2 className="ink-panel__title">{title}</h2>}
      {children}
    </aside>
  )
}
