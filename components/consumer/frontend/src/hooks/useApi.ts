/**
 * useApi — axios wrapper with automatic JWT injection.
 *
 * All methods return typed response data or throw on error.
 * The hook reads the token from localStorage on every call so it always
 * uses the current token without needing a React context.
 */

import { useCallback } from 'react'
import axios from 'axios'
import type { ConsumerStatus, MessagePage, MessageQueryParams } from '../types'

const TOKEN_KEY = 'hamq-consumer-token'

function getHeaders(): Record<string, string> {
  const token = localStorage.getItem(TOKEN_KEY)
  return token ? { Authorization: `Bearer ${token}` } : {}
}

export function useApi() {
  /** GET /api/status */
  const getStatus = useCallback(async (): Promise<ConsumerStatus> => {
    const resp = await axios.get<ConsumerStatus>('/api/status', {
      headers: getHeaders(),
    })
    return resp.data
  }, [])

  /** POST /api/start */
  const startConsumer = useCallback(async (): Promise<void> => {
    await axios.post('/api/start', {}, { headers: getHeaders() })
  }, [])

  /** POST /api/stop */
  const stopConsumer = useCallback(async (): Promise<void> => {
    await axios.post('/api/stop', {}, { headers: getHeaders() })
  }, [])

  /** GET /api/messages with optional filters */
  const getMessages = useCallback(
    async (params: MessageQueryParams): Promise<MessagePage> => {
      const query: Record<string, string | number> = {
        page: params.page,
        page_size: params.page_size,
      }
      if (params.producer_id) query.producer_id = params.producer_id
      if (params.seq_from != null) query.seq_from = params.seq_from
      if (params.seq_to != null) query.seq_to = params.seq_to

      const resp = await axios.get<MessagePage>('/api/messages', {
        headers: getHeaders(),
        params: query,
      })
      return resp.data
    },
    []
  )

  /** GET /api/messages/recent */
  const getRecentMessages = useCallback(async (limit = 100) => {
    const resp = await axios.get('/api/messages/recent', {
      headers: getHeaders(),
      params: { limit },
    })
    return resp.data
  }, [])

  /** GET /api/messages/missing */
  const getMissingSequences = useCallback(
    async (producerId: string, seqFrom: number, seqTo: number): Promise<number[]> => {
      const resp = await axios.get<number[]>('/api/messages/missing', {
        headers: getHeaders(),
        params: {
          producer_id: producerId,
          seq_from: seqFrom,
          seq_to: seqTo,
        },
      })
      return resp.data
    },
    []
  )

  return {
    getStatus,
    startConsumer,
    stopConsumer,
    getMessages,
    getRecentMessages,
    getMissingSequences,
  }
}
