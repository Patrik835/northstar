export type User = {
  id: string;
  username: string;
  email: string | null;
  is_admin: boolean;
};

export type AllocationItem = {
  label: string;
  value_eur: string;
  percentage: string;
};

export type DashboardSummary = {
  currency: "EUR";
  total_value_eur: string;
  by_source: AllocationItem[];
  by_asset_type: AllocationItem[];
  positions_count: number;
  data_notice: string | null;
};

export type Broker =
  | "trading212"
  | "trading212_crypto"
  | "etoro"
  | "binance";

export type Connection = {
  id: string;
  broker: Broker;
  credential_hint: string;
  status: "pending" | "active" | "limited" | "error" | "disabled";
  last_error: string | null;
  last_synced_at: string | null;
  last_sync_attempt_at: string | null;
  last_successful_sync_at: string | null;
  freshness_status: "never_synced" | "fresh" | "stale";
  is_stale: boolean;
  stale_after: string | null;
};

export type ConnectionGuide = {
  broker: Broker;
  connection_type: "api" | "csv";
  category: string;
  description: string;
  credential_fields: string[];
  credential_labels: Record<string, string>;
  security_notice: string;
  setup_steps: string[];
  tutorial_url: string;
};

export type CryptoCsvImportResult = {
  connection: Connection;
  rows_read: number;
  transactions_added: number;
  duplicates_skipped: number;
  positions_imported: number;
  warnings: string[];
};

export type AssetType = "stock" | "etf" | "crypto" | "cash" | "other";

export type HoldingSource = {
  broker: Broker;
  connection_id: string;
  provider_instrument_id: string;
  provider_symbol: string;
  provider_name: string | null;
  canonical_instrument_id: string | null;
  canonical_symbol: string;
  canonical_name: string;
  canonical_isin: string | null;
  quantity: string;
  average_price: string | null;
  current_value: string;
  currency: string;
  current_value_eur: string;
  reported_pnl: string | null;
  reported_pnl_eur: string | null;
  instrument_percentage: string;
  last_synced_at: string | null;
  valued_at: string | null;
  valuation_source: string;
  is_estimated: boolean;
  freshness_status: "fresh" | "stale";
  is_stale: boolean;
};

export type Holding = {
  key: string;
  grouping: "instrument" | "company";
  instrument_count: number;
  canonical_instrument_id: string | null;
  symbol: string;
  symbols: string[];
  name: string;
  isin: string | null;
  asset_type: AssetType;
  total_quantity: string | null;
  total_value_eur: string;
  reported_pnl_eur: string | null;
  reported_pnl_source_count: number;
  portfolio_percentage: string;
  source_count: number;
  as_of: string | null;
  is_stale: boolean;
  stale_source_count: number;
  has_estimated_value: boolean;
  sources: HoldingSource[];
};

export type ReconciliationWarning = {
  broker: Broker;
  connection_id: string;
  difference_percent: string | null;
  checked_at: string | null;
  message: string;
};

export type HoldingsResponse = {
  currency: "EUR";
  total_value_eur: string;
  reported_pnl_eur: string | null;
  reported_pnl_position_count: number;
  instrument_count: number;
  position_count: number;
  unmatched_positions: number;
  as_of: string | null;
  stale_source_count: number;
  estimated_position_count: number;
  reconciliation_warnings: ReconciliationWarning[];
  sources: AllocationItem[];
  holdings: Holding[];
};
