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

export type Broker = "trading212" | "trading212_crypto" | "etoro" | "binance";

export type Connection = {
  id: string;
  broker: Broker;
  credential_hint: string;
  status: "pending" | "active" | "limited" | "error" | "disabled";
  last_error: string | null;
  last_synced_at: string | null;
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
  quantity: string;
  average_price: string | null;
  current_value: string;
  currency: string;
  current_value_eur: string;
  instrument_percentage: string;
  last_synced_at: string | null;
};

export type Holding = {
  key: string;
  canonical_instrument_id: string | null;
  symbol: string;
  name: string;
  isin: string | null;
  asset_type: AssetType;
  total_quantity: string;
  total_value_eur: string;
  portfolio_percentage: string;
  source_count: number;
  sources: HoldingSource[];
};

export type HoldingsResponse = {
  currency: "EUR";
  total_value_eur: string;
  instrument_count: number;
  position_count: number;
  unmatched_positions: number;
  sources: AllocationItem[];
  holdings: Holding[];
};
