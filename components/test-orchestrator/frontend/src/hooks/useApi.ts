import { useCallback } from 'react'

export function useApi(token: string | null) {
  const headers = useCallback(
    () => ({ 'Content-Type': 'application/json', Authorization: `Bearer ${token}` }),
    [token]
  )

  const getStatus = useCallback(async () => {
    const r = await fetch('/api/status', { headers: headers() })
    if (!r.ok) throw new Error(`status ${r.status}`)
    return r.json()
  }, [headers])

  const startTest = useCallback(async () => {
    const r = await fetch('/api/start', { method: 'POST', headers: headers() })
    if (!r.ok) throw new Error(`start ${r.status}`)
    return r.json()
  }, [headers])

  const stopTest = useCallback(async () => {
    const r = await fetch('/api/stop', { method: 'POST', headers: headers() })
    if (!r.ok) throw new Error(`stop ${r.status}`)
    return r.json()
  }, [headers])

  const updateConfig = useCallback(async (freq_hz?: number, counter_max?: number) => {
    const r = await fetch('/api/config', {
      method: 'PUT',
      headers: headers(),
      body: JSON.stringify({ freq_hz, counter_max }),
    })
    if (!r.ok) throw new Error(`config ${r.status}`)
    return r.json()
  }, [headers])

  return { getStatus, startTest, stopTest, updateConfig }
}
