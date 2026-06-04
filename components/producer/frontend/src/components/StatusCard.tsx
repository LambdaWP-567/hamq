/**
 * StatusCard — Reusable metric display card.
 *
 * Shows a labelled value with an optional colour-coded status badge.
 */

import React from 'react'

type StatusVariant = 'default' | 'success' | 'warning' | 'danger' | 'info'

interface StatusCardProps {
  /** Card title / label */
  label: string
  /** Primary value to display */
  value: string | number
  /** Optional description below the value */
  description?: string
  /** Colour theme */
  variant?: StatusVariant
  /** Optional icon (SVG element) */
  icon?: React.ReactNode
}

const variantClasses: Record<StatusVariant, { border: string; icon: string; value: string }> = {
  default: { border: 'border-gray-200', icon: 'text-gray-400', value: 'text-gray-900' },
  success: { border: 'border-green-200', icon: 'text-green-500', value: 'text-green-700' },
  warning: { border: 'border-yellow-200', icon: 'text-yellow-500', value: 'text-yellow-700' },
  danger:  { border: 'border-red-200',  icon: 'text-red-500',   value: 'text-red-700'   },
  info:    { border: 'border-blue-200', icon: 'text-blue-500',  value: 'text-blue-700'  },
}

export default function StatusCard({
  label,
  value,
  description,
  variant = 'default',
  icon,
}: StatusCardProps) {
  const classes = variantClasses[variant]

  return (
    <div className={`card border-l-4 ${classes.border}`}>
      <div className="flex items-start justify-between">
        <div className="flex-1 min-w-0">
          <p className="text-xs font-medium text-gray-500 uppercase tracking-wide truncate">
            {label}
          </p>
          <p className={`mt-1 text-2xl font-bold ${classes.value} tabular-nums`}>
            {typeof value === 'number' ? value.toLocaleString() : value}
          </p>
          {description && (
            <p className="mt-1 text-xs text-gray-400 truncate">{description}</p>
          )}
        </div>
        {icon && (
          <div className={`ml-3 flex-shrink-0 ${classes.icon}`}>
            {icon}
          </div>
        )}
      </div>
    </div>
  )
}
