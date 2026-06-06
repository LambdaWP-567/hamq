import { createContext, useContext } from 'react'

export type ToastType = 'success' | 'error' | 'info'

export interface Toast {
  id: number
  message: string
  type: ToastType
}

export interface ToastCtx {
  showToast: (message: string, type?: ToastType) => void
}

export const ToastContext = createContext<ToastCtx>({ showToast: () => {} })

export const useToast = () => useContext(ToastContext)
