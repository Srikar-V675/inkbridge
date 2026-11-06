import type { ButtonHTMLAttributes } from 'react'
import './Button.css'

export type ButtonVariant = 'primary' | 'secondary' | 'quiet'

export function Button({
  variant = 'primary',
  className,
  type = 'button',
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant }) {
  const cls = ['ink-button', `ink-button--${variant}`, className].filter(Boolean).join(' ')
  return <button type={type} className={cls} {...rest} />
}
