import { useEffect } from 'react'
import { Button } from './Button.tsx'
import { scheduleDismiss } from './toast.ts'
import './Toast.css'

export function Toast({
  message,
  actionLabel,
  onAction,
  onDismiss,
  durationMs,
}: {
  message: string
  actionLabel?: string
  onAction?: () => void
  onDismiss: () => void
  durationMs?: number
}) {
  useEffect(() => scheduleDismiss(onDismiss, durationMs), [onDismiss, durationMs])
  return (
    <div className="ink-toast" role="status">
      <span>{message}</span>
      {actionLabel && (
        <Button variant="quiet" onClick={onAction}>
          {actionLabel}
        </Button>
      )}
    </div>
  )
}
