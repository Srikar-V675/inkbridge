import './StatusDot.css'

/** `risk` is the alarm colour: only for ink that exists only in memory (DESIGN.md Colors). */
export function StatusDot({ tone = 'sending' }: { tone?: 'sending' | 'risk' }) {
  return <span className={`ink-status-dot ink-status-dot--${tone}`} aria-hidden />
}
