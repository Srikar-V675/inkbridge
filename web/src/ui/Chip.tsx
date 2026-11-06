import type { ButtonHTMLAttributes } from 'react'
import './Chip.css'

/** The offer pill: the agent has something to show. */
export function Chip({ children, className, type = 'button', ...rest }: ButtonHTMLAttributes<HTMLButtonElement>) {
  const cls = ['ink-chip', className].filter(Boolean).join(' ')
  return (
    <button type={type} className={cls} {...rest}>
      <span className="ink-chip__dot" aria-hidden />
      {children}
    </button>
  )
}
