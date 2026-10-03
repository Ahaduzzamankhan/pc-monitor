import type { Metadata } from 'next'

import { Sidebar } from '@/components/Sidebar'

export const metadata: Metadata = {
  title: 'PC Monitor - Dashboard',
}

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="app-shell">
      <Sidebar />
      <div className="main">{children}</div>
    </div>
  )
}