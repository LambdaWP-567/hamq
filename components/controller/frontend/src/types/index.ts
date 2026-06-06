// ---------------------------------------------------------------------------
// Kubernetes resource types
// ---------------------------------------------------------------------------

export interface PodInfo {
  name: string
  namespace: string
  status: string
  node: string
  ready: boolean
  restart_count: number
}

export interface NodeCondition {
  type: string
  status: string
  message: string
}

export interface NodeInfo {
  name: string
  status: string
  schedulable: boolean
  roles: string[]
  conditions: NodeCondition[]
  kvm_available: boolean
  network_cut: boolean
}

export interface NetworkPolicyInfo {
  name: string
  namespace: string
  pod_selector: Record<string, unknown>
  ingress_rules: Record<string, unknown>[]
  egress_rules: Record<string, unknown>[]
}

// ---------------------------------------------------------------------------
// Chaos engine types
// ---------------------------------------------------------------------------

export type ChaosAction = 'random_pod_delete' | 'node_drain' | 'network_partition'

export interface ChaosConfig {
  enabled: boolean
  action: ChaosAction
  target_namespace: string
  dry_run: boolean
}

// ---------------------------------------------------------------------------
// Event / audit types
// ---------------------------------------------------------------------------

export type EventType =
  | 'pod_restart'
  | 'pod_delete'
  | 'node_cordon'
  | 'node_drain'
  | 'node_uncordon'
  | 'network_partition_create'
  | 'network_partition_delete'
  | 'chaos_random'

export type EventStatus = 'pending' | 'success' | 'failed'

export interface ClusterEvent {
  event_id: string
  timestamp: string
  event_type: EventType
  target: string
  namespace: string
  status: EventStatus
  details: string
}

// ---------------------------------------------------------------------------
// Databus metrics
// ---------------------------------------------------------------------------

export interface DataBusMetrics {
  lag: number
  producer_rate: number
  producer_sent: number
  consumer_received: number
  producer_available: boolean
  consumer_available: boolean
}

// ---------------------------------------------------------------------------
// Status aggregate
// ---------------------------------------------------------------------------

export interface ControllerStatus {
  controller_id: string
  k8s_connected: boolean
  kafka_pods: PodInfo[]
  nodes: NodeInfo[]
  active_partitions: NetworkPolicyInfo[]
  recent_events: ClusterEvent[]
  chaos_enabled: boolean
  databus: DataBusMetrics
}

// ---------------------------------------------------------------------------
// Auth types
// ---------------------------------------------------------------------------

export interface AuthToken {
  access_token: string
  token_type: string
}

export interface LoginRequest {
  username: string
  password: string
}

// ---------------------------------------------------------------------------
// Network partition creation
// ---------------------------------------------------------------------------

export interface NetworkPartitionRequest {
  name: string
  target_namespace: string
  pod_selector: Record<string, string>
}

// ---------------------------------------------------------------------------
// Error type
// ---------------------------------------------------------------------------

export interface ApiError {
  detail: string | { msg: string; type: string }[]
}

// ---------------------------------------------------------------------------
// UI state helpers
// ---------------------------------------------------------------------------

export type LoadingState = 'idle' | 'loading' | 'success' | 'error'

export interface AsyncState<T> {
  data: T | null
  loading: boolean
  error: string | null
}
