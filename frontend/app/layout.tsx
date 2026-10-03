import type { Metadata } from 'next'
import './globals.css'

export const metadata: Metadata = {
  title: 'PC Monitor',
  description: 'Personal hardware telemetry dashboard for Windows PCs',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  )
}