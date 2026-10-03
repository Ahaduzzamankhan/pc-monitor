'use client'

import { StatusBadge } from './StatusBadge'

export interface NavbarProps {
  title: string
  subtitle?: string
  onlineCount?: number
  totalCount?: number
  lastUpdated?: Date | null
  refreshing?: boolean
  actions?: React.ReactNode
}

/** Page header with live status and manual refresh affordance. */
export function Navbar({
  title,
  subtitle,
  onlineCount,
  totalCount,
  lastUpdated,
  refreshing,
  actions,
}: NavbarProps) {
  return (
    <header className="navbar">
      <div>
        <h1 className="navbar__title">{title}</h1>
        {subtitle ? <p className="small muted" style={{ margin: 0 }}>{subtitle}</p> : null}
      </div>

      <div className="navbar__meta">
        {typeof onlineCount === 'number' && typeof totalCount === 'number' ? (
          <span data-testid="device-count">
            {onlineCount} online / {totalCount} total
          </span>
        ) : null}
        <StatusBadge
          online={!refreshing}
          status={refreshing ? 'refreshing' : onlineCount ? 'live' : 'idle'}
          pulse={false}
        />
        {lastUpdated ? (
          <span className="muted" data-testid="last-updated">
            Updated {lastUpdated.toLocaleTimeString()}
          </span>
        ) : null}
        {actions}
      </div>
    </header>
  )
}

export default Navbar