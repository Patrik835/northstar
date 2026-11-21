// Pure helpers for the Holdings views: formatting, grouping and P/L math.
import type {
  AssetType,
  HoldingSource,
  InvestmentPerformanceBreakdown,
} from "../../api/types";

import { formatEur } from "../../lib/format";

// Same € format as the rest of the app (no cents from €1,000 up).
export const eur = { format: formatEur };
export const quantity = new Intl.NumberFormat("en-IE", { maximumFractionDigits: 8 });
export const assetLabels: Record<AssetType, string> = {
  stock: "Stock",
  etf: "ETF",
  crypto: "Crypto",
  cash: "Cash",
  other: "Other",
};

export type AssetGroup = "all" | "equities" | "crypto" | "other";
export type SortKey = "value" | "pnl";
export type SortDirection = "asc" | "desc";

export function inGroup(type: AssetType, group: AssetGroup) {
  if (group === "all") return true;
  if (group === "equities") return type === "stock" || type === "etf";
  if (group === "crypto") return type === "crypto";
  return type === "cash" || type === "other";
}

export function sourceValue(source: HoldingSource) {
  return Number(source.current_value_eur);
}

export function sourceQuantity(source: HoldingSource) {
  return Number(source.quantity);
}

export function originalMoney(value: string, currency: string) {
  const number = Number(value);
  try {
    return new Intl.NumberFormat("en-IE", {
      style: "currency",
      currency,
      maximumFractionDigits: 4,
    }).format(number);
  } catch {
    return `${quantity.format(number)} ${currency}`;
  }
}

export function timestamp(value: string | null) {
  if (!value) return "Awaiting first valuation";
  return new Date(value).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

export function valuationLabel(source: HoldingSource) {
  if (source.valuation_source === "manual_cost") return "Valued at purchase cost";
  if (source.valuation_source === "manual") return "Manual valuation";
  if (source.valuation_source === "last_trade") return "Estimated from last trade";
  if (source.valuation_source === "market") return "Market price";
  if (source.valuation_source === "statement") return "Imported statement";
  return "Provider value";
}

export type PnlSummary = {
  value: number;
  /** What was paid for the positions this gain/loss covers; percentage = value / costBasis. */
  costBasis: number;
  percentage: number | null;
  sourceCount: number;
  totalSources: number;
  calculatedCount: number;
};

export type SourcePnl = {
  valueEur: number;
  kind: "calculated" | "reported" | "manual";
};

export function preferredSourcePnl(source: HoldingSource): SourcePnl | null {
  if (source.performance.open_pnl_eur === null) return null;
  return {
    valueEur: Number(source.performance.open_pnl_eur),
    kind: source.broker === "manual"
      ? "manual"
      : source.performance.open_pnl_source === "calculated"
        ? "calculated"
        : "reported",
  };
}

export function summarizePnl(sources: HoldingSource[]): PnlSummary | null {
  const available = sources.flatMap((source) => {
    const pnl = preferredSourcePnl(source);
    return pnl ? [{ source, pnl }] : [];
  });
  if (!available.length) return null;
  const value = available.reduce(
    (total, item) => total + item.pnl.valueEur,
    0,
  );
  const coveredValue = available.reduce(
    (total, item) => total + sourceValue(item.source),
    0,
  );
  const costBasis = coveredValue - value;
  return {
    value,
    costBasis,
    percentage: costBasis > 0 ? (value * 100) / costBasis : null,
    sourceCount: available.length,
    totalSources: sources.length,
    calculatedCount: available.filter((item) => item.pnl.kind === "calculated").length,
  };
}

export function combinePerformance(sources: HoldingSource[]): InvestmentPerformanceBreakdown {
  const items = sources.map((source) => source.performance);
  const sum = (values: (string | null)[], requireAll = false): string | null => {
    const known = values.filter((value): value is string => value !== null);
    if (!known.length || (requireAll && known.length !== values.length)) return null;
    return String(known.reduce((total, value) => total + Number(value), 0));
  };
  const complete = items.every((item) => item.coverage === "complete");
  const cost = sum(items.map((item) => item.cost_basis_eur), true);
  const open = sum(items.map((item) => item.open_pnl_eur));
  const realized = sum(items.map((item) => item.realized_pnl_eur));
  const income = sum(items.map((item) => item.income_eur)) ?? "0";
  const fees = sum(items.map((item) => item.fees_eur)) ?? "0";
  const kinds = new Set(items.map((item) => item.open_pnl_source).filter((kind) => kind !== "unavailable"));
  return {
    cost_basis_eur: cost,
    open_pnl_eur: open,
    open_pnl_percentage: open !== null && cost !== null && Number(cost) > 0
      ? String(Number(open) * 100 / Number(cost)) : null,
    open_pnl_source: kinds.size === 1 ? [...kinds][0] : kinds.size ? "mixed" : "unavailable",
    realized_pnl_eur: realized,
    income_eur: income,
    fees_eur: fees,
    total_return_eur: complete && items.every((item) => item.open_pnl_eur !== null && item.realized_pnl_eur !== null)
      ? String(Number(open) + Number(realized) + Number(income) - Number(fees)) : null,
    coverage: complete ? "complete" : items.some((item) => item.coverage !== "unavailable") ? "partial" : "unavailable",
    missing_event_count: items.reduce((total, item) => total + item.missing_event_count, 0),
  };
}

export { formatChange as signedMoney, formatPercentChange as signedPercentage } from "../../lib/format";
