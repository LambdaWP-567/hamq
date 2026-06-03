/**
 * TypeScript interfaces for the HAMq Producer API.
 *
 * These mirror the Pydantic models defined in the backend (app/models.py)
 * to provide end-to-end type safety in the frontend.
 */

/** Inner message payload carrying the actual data and its checksum. */
export interface MessagePayload {
  data: string
  checksum: string
}

/** A single HAMq message as returned by GET /api/messages/recent. */
export interface Message {
  id: string
  sequence: number
  producer_id: string
  timestamp: string
  frequency_hz: number
  payload: MessagePayload
}

/** Snapshot of the producer's current state (REST + WebSocket). */
export interface ProducerStatus {
  producer_id: string
  running: boolean
  frequency_hz: number
  sequence_counter: number
  buffered_count: number
  sent_count: number
  error_count: number
  kafka_connected: boolean
}

/** JWT token response from POST /api/auth/login. */
export interface AuthToken {
  access_token: string
  token_type: string
}

/** Generic API response wrapper for error handling. */
export interface ApiResponse<T> {
  data?: T
  error?: string
  status: number
}

/** Data point for the message rate chart (time-series). */
export interface RateDataPoint {
  /** Unix timestamp in milliseconds (for Recharts XAxis) */
  time: number
  /** Messages sent in the last second */
  sent: number
  /** Messages currently buffered */
  buffered: number
}
