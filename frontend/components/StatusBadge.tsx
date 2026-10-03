'use client'

import { cn } from '@/lib/utils'

export interface StatusBadgeProps {
  online: boolean
  status?: string
  /** Adds a subtle pulse to online devices. */
  pulse?: boolean
  className?: string
}

/** Compact ONLINE/OFFLINE pill used on cards, headers and tables. */
export function StatusBadge({ online, status, pulse = true, className }: StatusBadgeProps) {
  const label = status ?? (online ? 'online' : 'offline')
  return (
    <span
      data-testid="status-badge"
      data-status={label}
      className={cn(
        'badge',
        online ? 'badge--online' : 'badge--offline',
        pulse && online && 'badge--pulse',
        className,
      )}
    >
      <span className="badge__dot" aria-hidden="true" />
      {label}
    </span>
  )
}

export default StatusBadge