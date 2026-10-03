import Link from 'next/link'

export default function NotFound() {
  return (
    <main className="content" style={{ padding: 60 }}>
      <div className="state">
        <span className="state__title">Page not found</span>
        <span>That route does not exist in PC Monitor.</span>
        <Link className="button" href="/dashboard">
          Back to the dashboard
        </Link>
      </div>
    </main>
  )
}