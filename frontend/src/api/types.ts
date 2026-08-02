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

export type Broker = "trading212" | "etoro" | "binance";

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
  credential_fields: string[];
  security_notice: string;
  setup_steps: string[];
  tutorial_url: string;
};
