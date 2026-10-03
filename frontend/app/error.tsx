'use client'

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  return (
    <main className="content" style={{ padding: 40 }}>
      <div className="state state--error" role="alert">
        <span className="state__title">The dashboard hit an unexpected error</span>
        <span>{error.message}</span>
        <button type="button" className="button" onClick={reset}>
          Try again
        </button>
      </div>
    </main>
  )
}