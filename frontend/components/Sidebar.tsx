'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'

import { cn } from '@/lib/utils'

export interface NavItem {
  href: string
  label: string
  icon: string
}

export const NAV_ITEMS: NavItem[] = [
  { href: '/dashboard', label: 'Overview', icon: '◧' },
  { href: '/dashboard/devices', label: 'Devices', icon: '▤' },
  { href: '/dashboard/logs', label: 'Activity', icon: '≡' },
  { href: '/dashboard/settings', label: 'Settings', icon: '⚙' },
]

/** Persistent navigation for the dashboard shell. */
export function Sidebar({ version = '1.0.0' }: { version?: string }) {
  const pathname = usePathname()

  return (
    <aside className="sidebar">
      <div className="sidebar__brand">
        <span className="sidebar__logo">PC</span>
        PC Monitor
      </div>
      <p className="sidebar__tagline">Hardware telemetry</p>

      <nav className="sidebar__nav" aria-label="Dashboard">
        {NAV_ITEMS.map((item) => {
          const active =
            item.href === '/dashboard'
              ? pathname === '/dashboard'
              : pathname.startsWith(item.href)
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn('sidebar__link', active && 'sidebar__link--active')}
              aria-current={active ? 'page' : undefined}
            >
              <span aria-hidden="true">{item.icon}</span>
              {item.label}
            </Link>
          )
        })}
      </nav>

      <div className="sidebar__footer">
        <span>Monitoring only - no remote control.</span>
        <span>Agent v{version}</span>
      </div>
    </aside>
  )
}

export default Sidebar