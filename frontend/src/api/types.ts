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
  | "binance"
  | "xtb";

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

export type StatementImportResult = {
  connection: Connection;
  rows_read: number;
  transactions_added: number;
  duplicates_skipped: number;
  positions_imported: number;
  warnings: string[];
};

export type AssetType = "stock" | "etf" | "crypto" | "cash" | "other";

export type InvestmentPerformanceBreakdown = {
  cost_basis_eur: string | null;
  open_pnl_eur: string | null;
  open_pnl_percentage: string | null;
  open_pnl_source: "provider" | "calculated" | "mixed" | "unavailable";
  realized_pnl_eur: string | null;
  income_eur: string;
  fees_eur: string;
  total_return_eur: string | null;
  coverage: "complete" | "partial" | "unavailable";
  missing_event_count: number;
};

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
  calculated_cost_eur: string | null;
  calculated_gain_eur: string | null;
  calculated_gain_percentage: string | null;
  gain_coverage: "complete" | "partial" | "unavailable";
  performance: InvestmentPerformanceBreakdown;
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
  calculated_cost_eur: string | null;
  calculated_gain_eur: string | null;
  calculated_gain_percentage: string | null;
  gain_coverage: "complete" | "partial" | "unavailable";
  performance: InvestmentPerformanceBreakdown;
  category: string | null;
  tags: string[];
  notes: string | null;
  target_allocation_percentage: string | null;
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
  performance: InvestmentPerformanceBreakdown;
  net_contributions_eur: string | null;
  external_flow_coverage: "complete" | "partial" | "unavailable";
};

export type TransactionType =
  | "buy"
  | "sell"
  | "dividend"
  | "deposit"
  | "withdrawal"
  | "fee"
  | "other";

export type ActivityItem = {
  id: string;
  broker: Broker;
  connection_id: string;
  holding_key: string | null;
  symbol: string;
  name: string | null;
  transaction_type: TransactionType;
  quantity: string | null;
  price: string | null;
  value: string;
  value_eur: string | null;
  is_estimated_fx: boolean;
  currency: string;
  executed_at: string;
};

export type ActivityResponse = {
  items: ActivityItem[];
  total: number;
  offset: number;
  limit: number;
  brokers: Broker[];
  transaction_types: TransactionType[];
  summary: {
    bought: ActivityTotal;
    sold: ActivityTotal;
    dividends: ActivityTotal;
    deposited: ActivityTotal;
  };
};

export type ActivityTotal = {
  value_eur: string;
  event_count: number;
  missing_eur_count: number;
  estimated_eur_count: number;
  native_values: Array<{
    currency: string;
    value: string;
    event_count: number;
  }>;
};

export type HoldingMetadata = {
  holding_key: string;
  category: string | null;
  tags: string[];
  notes: string | null;
  target_allocation_percentage: string | null;
  updated_at: string | null;
};

export type PortfolioHistoryPoint = {
  date: string;
  total_value_eur: string;
  net_invested_eur: string;
  invested_value_eur: string;
};

export type ReturnMetric = {
  percentage: string | null;
  status: "available" | "partial" | "unavailable";
  message: string | null;
};

export type PortfolioPerformance = {
  range: "1w" | "1m" | "3m" | "6m" | "1y" | "5y" | "all";
  currency: "EUR";
  start_date: string | null;
  end_date: string | null;
  sampling: "daily" | "weekly_average" | "monthly_average" | "adaptive_average";
  history_method: "observed" | "reconstructed";
  points: PortfolioHistoryPoint[];
  money_weighted_return: ReturnMetric;
  time_weighted_return: ReturnMetric;
  attribution: {
    total_return_eur: string | null;
    capital_gain_eur: string | null;
    income_eur: string;
    fees_eur: string;
    currency_movement_eur: string | null;
    status: "available" | "estimated" | "partial" | "unavailable";
    message: string | null;
  };
  missing_fx_transaction_count: number;
  notices: string[];
};

export type AnalyticsCoverage = "available" | "partial" | "unavailable";

export type AllocationBreakdown = {
  dimension: "asset_type" | "holding" | "broker" | "currency" | "sector" | "geography";
  items: AllocationItem[];
  scope_value_eur: string;
  covered_value_eur: string;
  coverage_percentage: string;
  status: AnalyticsCoverage;
  message: string | null;
};

export type AnalyticsPerformer = {
  holding_key: string;
  symbol: string;
  name: string;
  current_value_eur: string;
  open_pnl_eur: string;
  open_pnl_percentage: string;
  contribution_percentage_points: string;
  source: "provider" | "calculated" | "mixed";
};

export type AnalyticsResponse = {
  range: PortfolioPerformance["range"];
  allocations: AllocationBreakdown[];
  performance: {
    best: AnalyticsPerformer[];
    worst: AnalyticsPerformer[];
    contributors: AnalyticsPerformer[];
    coverage_percentage: string;
    message: string;
  };
  benchmark: {
    selected_instrument_id: string | null;
    selected_symbol: string | null;
    selected_name: string | null;
    options: Array<{ instrument_id: string; symbol: string; name: string }>;
    points: Array<{
      date: string;
      portfolio_return_percentage: string;
      benchmark_return_percentage: string;
    }>;
    portfolio_return_percentage: string | null;
    benchmark_return_percentage: string | null;
    relative_return_percentage: string | null;
    status: AnalyticsCoverage;
    message: string;
  };
  risk: {
    maximum_drawdown_percentage: string | null;
    annualized_volatility_percentage: string | null;
    largest_holding_percentage: string;
    top_five_percentage: string;
    concentration_hhi: string;
    effective_holdings: string;
    diversification_score: string;
    observation_count: number;
    status: AnalyticsCoverage;
    message: string;
  };
  targets: {
    target_total_percentage: string;
    unallocated_percentage: string;
    items: Array<{
      holding_key: string;
      symbol: string;
      name: string;
      current_percentage: string;
      target_percentage: string | null;
      drift_percentage_points: string | null;
      current_value_eur: string;
      target_value_eur: string | null;
      difference_eur: string | null;
      action: "add" | "reduce" | "on_target" | "not_set";
    }>;
    message: string;
  };
};
