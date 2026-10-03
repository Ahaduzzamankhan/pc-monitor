'use client'

import { HISTORY_RANGES, type HistoryRange } from '@/lib/types'
import { cn } from '@/lib/utils'

export interface RangeSelectorProps {
  value: HistoryRange
  onChange: (range: HistoryRange) => void
  disabled?: boolean
  available?: HistoryRange[]
}

const LABELS: Record<HistoryRange, string> = {
  '1h': '1h',
  '6h': '6h',
  '24h': '24h',
  '7d': '7d',
}

/** 1h / 6h / 24h / 7d selector. The backend refuses anything longer. */
export function RangeSelector({
  value,
  onChange,
  disabled,
  available = HISTORY_RANGES,
}: RangeSelectorProps) {
  return (
    <div className="range-selector" role="group" aria-label="History range">
      {HISTORY_RANGES.map((range) => {
        const active = range === value
        const isAvailable = available.includes(range)
        return (
          <button
            key={range}
            type="button"
            data-testid={`range-${range}`}
            className={cn('range-selector__button', active && 'range-selector__button--active')}
            onClick={() => onChange(range)}
            disabled={disabled || !isAvailable}
            aria-pressed={active}
            title={isAvailable ? undefined : 'Not available with the current retention window'}
          >
            {LABELS[range]}
          </button>
        )
      })}
    </div>
  )
}

export default RangeSelector