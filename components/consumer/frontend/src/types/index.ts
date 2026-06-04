/**
 * TypeScript types matching the HAMq Consumer backend Pydantic models.
 * Keep in sync with app/models.py.
 */

// --------------------------------------------------------------------------- //
//  Domain types
// --------------------------------------------------------------------------- //

/** One message as stored in SQLite and served by GET /api/messages. */
export interface ReceivedMessage {
  id: string
  sequence: number
  producer_id: string
  received_at: string    // ISO-8601 UTC
  timestamp: string      // ISO-8601 UTC (original producer timestamp)
  frequency_hz: number
  payload_data: string
  checksum_valid: boolean
}

/** Real-time operational status of the consumer. */
export interface ConsumerStatus {
  consumer_id: string
  running: boolean
  kafka_connected: boolean
  received_count: number
  last_sequence_by_producer: Record<string, number>
  lag_estimate: number
  checksum_errors: number
}

/** Paginated list of received messages. */
export interface MessagePage {
  messages: ReceivedMessage[]
  total: number
  page: number
  page_size: number
}

// --------------------------------------------------------------------------- //
//  Auth types
// --------------------------------------------------------------------------- //

export interface LoginRequest {
  username: string
  password: string
}

export interface TokenResponse {
  access_token: string
  token_type: string
  expires_in: number
}

// --------------------------------------------------------------------------- //
//  WebSocket push types
// --------------------------------------------------------------------------- //

/** Message sent by the WebSocket endpoint every second. */
export interface StatusUpdate {
  type: 'status_update'
  status: ConsumerStatus
  recent_messages: ReceivedMessage[]
}

// --------------------------------------------------------------------------- //
//  Chart data types
// --------------------------------------------------------------------------- //

/** One data point for the receive-rate chart. */
export interface ReceiveRatePoint {
  time: string      // formatted HH:MM:SS
  rate: number      // messages per second (computed from delta)
  received: number  // absolute received_count at this sample
}

// --------------------------------------------------------------------------- //
//  Query param types
// --------------------------------------------------------------------------- //

export interface MessageQueryParams {
  producer_id?: string
  seq_from?: number
  seq_to?: number
  page: number
  page_size: number
}
