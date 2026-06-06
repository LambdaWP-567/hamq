import React, { useState, useCallback, useRef } from 'react'
import { CheckCircle2, XCircle, Info, X } from 'lucide-react'
import { ToastContext } from '../hooks/useToast'
import type { Toast, ToastType } from '../hooks/useToast'

const ICONS = {
  success: <CheckCircle2 className="w-4 h-4 text-green-500 flex-shrink-0" />,
  error:   <XCircle     className="w-4 h-4 text-red-500   flex-shrink-0" />,
  info:    <Info        className="w-4 h-4 text-blue-500  flex-shrink-0" />,
}

const BG = {
  success: 'bg-green-50 dark:bg-green-900/30 border-green-200 dark:border-green-700 text-green-800 dark:text-green-200',
  error:   'bg-red-50   dark:bg-red-900/30   border-red-200   dark:border-red-700   text-red-800   dark:text-red-200',
  info:    'bg-blue-50  dark:bg-blue-900/30  border-blue-200  dark:border-blue-700  text-blue-800  dark:text-blue-200',
}

let _id = 0

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])
  const timers = useRef<Map<number, ReturnType<typeof setTimeout>>>(new Map())

  const remove = useCallback((id: number) => {
    setToasts(t => t.filter(x => x.id !== id))
    const timer = timers.current.get(id)
    if (timer) { clearTimeout(timer); timers.current.delete(id) }
  }, [])

  const showToast = useCallback((message: string, type: ToastType = 'success') => {
    const id = ++_id
    setToasts(t => [...t, { id, message, type }])
    const timer = setTimeout(() => remove(id), 4000)
    timers.current.set(id, timer)
  }, [remove])

  return (
    <ToastContext.Provider value={{ showToast }}>
      {children}
      <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2 max-w-sm w-full pointer-events-none">
        {toasts.map(toast => (
          <div
            key={toast.id}
            className={`flex items-start gap-2 px-4 py-3 rounded-xl border shadow-lg text-sm pointer-events-auto animate-in slide-in-from-bottom-2 duration-200 ${BG[toast.type]}`}
          >
            {ICONS[toast.type]}
            <span className="flex-1">{toast.message}</span>
            <button onClick={() => remove(toast.id)} className="opacity-50 hover:opacity-100 transition-opacity">
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}
