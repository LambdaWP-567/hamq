import { useMemo } from 'react'
import axios, { type AxiosInstance, type AxiosError } from 'axios'
import type {
  PodInfo,
  NodeInfo,
  NetworkPolicyInfo,
  ClusterEvent,
  ChaosConfig,
  NetworkPartitionRequest,
  ControllerStatus,
} from '../types'

const TOKEN_KEY = 'hamq_controller_token'

function createAxiosInstance(): AxiosInstance {
  const instance = axios.create({
    baseURL: '',
    headers: { 'Content-Type': 'application/json' },
    timeout: 15_000,
  })

  // Request interceptor — inject JWT from localStorage
  instance.interceptors.request.use((config) => {
    const token = localStorage.getItem(TOKEN_KEY)
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  })

  // Response interceptor — normalise error messages
  instance.interceptors.response.use(
    (response) => response,
    (error: AxiosError) => {
      if (error.response?.status === 401) {
        // Clear stale token and redirect to login
        localStorage.removeItem(TOKEN_KEY)
        window.location.href = '/login'
      }
      return Promise.reject(error)
    }
  )

  return instance
}

// ---------------------------------------------------------------------------
// API client hook
// ---------------------------------------------------------------------------

export function useApi() {
  const api = useMemo(() => createAxiosInstance(), [])

  return useMemo(
    () => ({
      // -----------------------------------------------------------------------
      // Status
      // -----------------------------------------------------------------------
      getStatus: async (): Promise<ControllerStatus> => {
        const { data } = await api.get<ControllerStatus>('/api/status')
        return data
      },

      // -----------------------------------------------------------------------
      // Pods
      // -----------------------------------------------------------------------
      listPods: async (): Promise<PodInfo[]> => {
        const { data } = await api.get<PodInfo[]>('/api/pods')
        return data
      },

      restartPod: async (name: string): Promise<ClusterEvent> => {
        const { data } = await api.post<ClusterEvent>(`/api/pods/${encodeURIComponent(name)}/restart`)
        return data
      },

      deletePod: async (name: string): Promise<ClusterEvent> => {
        const { data } = await api.post<ClusterEvent>(`/api/pods/${encodeURIComponent(name)}/delete`)
        return data
      },

      // -----------------------------------------------------------------------
      // Nodes
      // -----------------------------------------------------------------------
      listNodes: async (): Promise<NodeInfo[]> => {
        const { data } = await api.get<NodeInfo[]>('/api/nodes')
        return data
      },

      cordonNode: async (name: string): Promise<ClusterEvent> => {
        const { data } = await api.post<ClusterEvent>(`/api/nodes/${encodeURIComponent(name)}/cordon`)
        return data
      },

      uncordonNode: async (name: string): Promise<ClusterEvent> => {
        const { data } = await api.post<ClusterEvent>(`/api/nodes/${encodeURIComponent(name)}/uncordon`)
        return data
      },

      drainNode: async (name: string, ignoreDs = true, force = false): Promise<ClusterEvent> => {
        const { data } = await api.post<ClusterEvent>(
          `/api/nodes/${encodeURIComponent(name)}/drain?ignore_daemonsets=${ignoreDs}&force=${force}`
        )
        return data
      },

      // -----------------------------------------------------------------------
      // Network policies
      // -----------------------------------------------------------------------
      listNetworkPolicies: async (namespace?: string): Promise<NetworkPolicyInfo[]> => {
        const params = namespace ? `?namespace=${encodeURIComponent(namespace)}` : ''
        const { data } = await api.get<NetworkPolicyInfo[]>(`/api/network-policies${params}`)
        return data
      },

      createNetworkPartition: async (req: NetworkPartitionRequest): Promise<ClusterEvent> => {
        const { data } = await api.post<ClusterEvent>('/api/network-policies', req)
        return data
      },

      deleteNetworkPartition: async (name: string, namespace?: string): Promise<ClusterEvent> => {
        const params = namespace ? `?namespace=${encodeURIComponent(namespace)}` : ''
        const { data } = await api.delete<ClusterEvent>(
          `/api/network-policies/${encodeURIComponent(name)}${params}`
        )
        return data
      },

      // -----------------------------------------------------------------------
      // Chaos engine
      // -----------------------------------------------------------------------
      runChaos: async (config: ChaosConfig): Promise<ClusterEvent> => {
        const { data } = await api.post<ClusterEvent>('/api/chaos/run', config)
        return data
      },

      getChaosStatus: async (): Promise<ClusterEvent | null> => {
        const { data } = await api.get<ClusterEvent | null>('/api/chaos/status')
        return data
      },

      // -----------------------------------------------------------------------
      // Events
      // -----------------------------------------------------------------------
      getEvents: async (limit = 100, eventType?: string): Promise<ClusterEvent[]> => {
        const params = new URLSearchParams({ limit: String(limit) })
        if (eventType) params.set('event_type', eventType)
        const { data } = await api.get<ClusterEvent[]>(`/api/events?${params.toString()}`)
        return data
      },
    }),
    [api]
  )
}

// ---------------------------------------------------------------------------
// Error helper
// ---------------------------------------------------------------------------

export function extractErrorMessage(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const detail = (error.response?.data as Record<string, unknown> | undefined)?.['detail']
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail)) {
      return detail.map((d: Record<string, string>) => d['msg'] ?? String(d)).join('; ')
    }
    return error.message
  }
  if (error instanceof Error) return error.message
  return String(error)
}
