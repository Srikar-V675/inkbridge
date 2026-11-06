import type { ButtonHTMLAttributes, ReactNode } from 'react'
import './IconButton.css'

export function IconButton({
  label,
  children,
  className,
  type = 'button',
  ...rest
}: Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'aria-label'> & { label: string; children: ReactNode }) {
  const cls = ['ink-icon-button', className].filter(Boolean).join(' ')
  return (
    <button type={type} className={cls} aria-label={label} {...rest}>
      {children}
    </button>
  )
}
