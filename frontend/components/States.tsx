'use client'

export interface EmptyStateProps {
  title: string
  description?: string
  action?: React.ReactNode
}

/** Shown when a device has no telemetry in the selected range. */
export function EmptyState({ title, description, action }: EmptyStateProps) {
  return (
    <div className="state" data-testid="empty-state" role="status">
      <span className="state__title">{title}</span>
      {description ? <span>{description}</span> : null}
      {action}
    </div>
  )
}

export interface ErrorStateProps {
  title?: string
  message: string
  onRetry?: () => void
}

/** Shown when the API is unreachable or returns an error. */
export function ErrorState({ title = 'Something went wrong', message, onRetry }: ErrorStateProps) {
  return (
    <div className="state state--error" data-testid="error-state" role="alert">
      <span className="state__title">{title}</span>
      <span>{message}</span>
      {onRetry ? (
        <button type="button" className="button" onClick={onRetry}>
          Try again
        </button>
      ) : null}
    </div>
  )
}

export function LoadingState({ label = 'Loading…' }: { label?: string }) {
  return (
    <div className="state" data-testid="loading-state" role="status">
      <span className="spinner" aria-hidden="true" />
      <span>{label}</span>
    </div>
  )
}

export default EmptyState