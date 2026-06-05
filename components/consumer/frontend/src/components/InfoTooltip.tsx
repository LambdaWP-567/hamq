import React from 'react'

interface InfoTooltipProps {
  text: string
}

export default function InfoTooltip({ text }: InfoTooltipProps) {
  return (
    <span className="relative group inline-flex cursor-help ml-1 align-middle">
      <span className="inline-flex items-center justify-center h-3.5 w-3.5 rounded-full
                       bg-gray-300 dark:bg-gray-600 text-gray-700 dark:text-gray-200
                       text-[10px] font-bold leading-none select-none">
        i
      </span>
      <span className="pointer-events-none absolute z-20 left-1/2 -translate-x-1/2
                       bottom-full mb-1.5 w-60 rounded-lg bg-gray-900 dark:bg-gray-700
                       text-white text-xs px-3 py-2 shadow-lg
                       opacity-0 group-hover:opacity-100 transition-opacity duration-150
                       whitespace-normal text-left">
        {text}
      </span>
    </span>
  )
}
