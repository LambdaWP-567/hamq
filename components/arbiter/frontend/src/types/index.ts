/**
 * TypeScript type definitions for the HAMq Arbiter frontend.
 *
 * These types mirror the Pydantic models defined in the backend (app/models.py).
 * Keeping them in sync ensures type safety when calling the REST API.
 */

// ---------------------------------------------------------------------------
// Auth
// ---------------------------------------------------------------------------

export interface TokenResponse {
  access_token: string;
  token_type: string;
}

export interface LoginCredentials {
  username: string;
  password: string;
}

// ---------------------------------------------------------------------------
// Audit types
// ---------------------------------------------------------------------------

/** Severity level returned for each audit record */
export type AuditStatus = "ok" | "warning" | "critical";

/**
 * Lightweight audit summary returned from GET /api/audits.
 * Does NOT include missing_sequences to keep list responses small.
 */
export interface AuditSummary {
  audit_id: string;
  timestamp: string;
  producer_id: string;
  sent_count: number;
  received_count: number;
  loss_rate: number;
  status: AuditStatus;
}

/**
 * Full audit record returned from GET /api/audits/{audit_id}.
 * Includes the complete missing_sequences list.
 */
export interface AuditResult extends AuditSummary {
  missing_sequences: number[];
}

// ---------------------------------------------------------------------------
// Reconcile report
// ---------------------------------------------------------------------------

/** Per-producer result embedded inside a ReconcileReport */
export interface ProducerAuditResult {
  audit_id: string;
  producer_id: string;
  producer_url: string;
  sent_count: number;
  received_count: number;
  missing_count: number;
  missing_sequences: number[];
  loss_rate: number;
  status: AuditStatus;
}

/**
 * Aggregated result of one reconciliation pass.
 * Returned by POST /api/reconcile and broadcast over WebSocket.
 */
export interface ReconcileReport {
  report_id: string;
  timestamp: string;
  producers: ProducerAuditResult[];
  total_sent: number;
  total_received: number;
  total_missing: number;
  overall_loss_rate: number;
  duration_ms: number;
}

// ---------------------------------------------------------------------------
// Arbiter status
// ---------------------------------------------------------------------------

/** Live operational snapshot returned by GET /api/status */
export interface ArbiterStatus {
  arbiter_id: string;
  running: boolean;
  last_reconcile_at: string | null;
  last_loss_rate: number | null;
  producers_monitored: number;
  total_audits: number;
}

// ---------------------------------------------------------------------------
// Statistics
// ---------------------------------------------------------------------------

/** Aggregate statistics returned by GET /api/stats */
export interface AuditStats {
  total_audits: number;
  avg_loss_rate: number;
  worst_producer: string | null;
  worst_loss_rate: number;
  producers_tracked: number;
}

// ---------------------------------------------------------------------------
// WebSocket message envelope
// ---------------------------------------------------------------------------

/** WebSocket messages arrive as a discriminated union keyed on "type" */
export interface WsStatusMessage {
  type: "status";
  data: ArbiterStatus;
}

export interface WsReportMessage {
  type: "report";
  data: ReconcileReport;
}

export type WsMessage = WsStatusMessage | WsReportMessage;

// ---------------------------------------------------------------------------
// Chart data
// ---------------------------------------------------------------------------

/** Single data point for the loss rate time-series chart */
export interface LossRateDataPoint {
  timestamp: string;
  /** Formatted time label shown on the x-axis */
  timeLabel: string;
  /** Loss rate as a percentage (0–100) for Recharts display */
  lossRatePct: number;
  producer_id: string;
  status: AuditStatus;
}
