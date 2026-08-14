import { useEffect, useMemo, useState } from "react";
import { api } from "../../api/client";
import type {
  AllocationItem,
  DashboardSummary,
} from "../../api/types";
import { EmptyState } from "../../components/EmptyState";
import { Link } from "../../routing/Router";

const money = new Intl.NumberFormat("en-IE", {
  style: "currency", currency: "EUR", maximumFractionDigits: 2,
});
const sourceLabels: Record<string, string> = {
  trading212: "Trading 212",
  trading212_crypto: "Trading 212 Crypto",
  etoro: "eToro",
  binance: "Binance",
  xtb: "XTB",
};
const assetLabels: Record<string, string> = {
  stock: "Stocks",
  etf: "ETFs",
  crypto: "Crypto",
  cash: "Cash",
  other: "Other",
};
const allocationColors = ["#83e5b5", "#70a8f7", "#f1ba52", "#c19bf5", "#ed8f88"];

function SourceDonut({ items, total }: { items: AllocationItem[]; total: number }) {
  const segments = items.map((item, index) => ({
    item,
    percentage: Number(item.percentage),
    start: items
      .slice(0, index)
      .reduce((sum, previous) => sum + Number(previous.percentage), 0),
  }));
  return (
    <div className="source-donut-layout">
      <div className="donut-figure">
        <svg viewBox="0 0 140 140" role="img" aria-label="Allocation by source">
          <circle className="donut-track" cx="70" cy="70" r="54" pathLength="100" />
          {segments.map(({ item, percentage, start }, index) => (
              <circle
                key={item.label}
                className="donut-segment"
                cx="70" cy="70" r="54" pathLength="100"
                stroke={allocationColors[index % allocationColors.length]}
                strokeDasharray={`${Math.max(percentage - 0.6, 0)} ${100 - Math.max(percentage - 0.6, 0)}`}
                strokeDashoffset={-start}
              />
          ))}
        </svg>
        <span className="donut-center"><small>Total</small><strong>{money.format(total)}</strong></span>
      </div>
      <div className="allocation-legend">
        {items.map((item, index) => (
          <div key={item.label}>
            <i style={{ backgroundColor: allocationColors[index % allocationColors.length] }} />
            <span>{sourceLabels[item.label] ?? item.label}</span>
            <strong>{item.percentage}%</strong>
            <small>{money.format(Number(item.value_eur))}</small>
          </div>
        ))}
      </div>
    </div>
  );
}

function AssetAllocation({ items }: { items: AllocationItem[] }) {
  return (
    <div className="asset-allocation-list">
      {items.map((item, index) => (
        <div className="asset-allocation-row" key={item.label}>
          <span>{assetLabels[item.label] ?? item.label}</span>
          <strong>{item.percentage}%</strong>
          <div className="allocation-track">
            <i
              style={{
                width: `${Math.min(Number(item.percentage), 100)}%`,
                backgroundColor: allocationColors[index % allocationColors.length],
              }}
            />
          </div>
          <small>{money.format(Number(item.value_eur))}</small>
        </div>
      ))}
    </div>
  );
}

export function DashboardPage() {
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    api<DashboardSummary>("/dashboard/summary")
      .then(setSummary).catch((reason: Error) => setError(reason.message));
  }, []);
  const sourcesByAllocation = useMemo(
    () => [...(summary?.by_source ?? [])].sort(
      (left, right) => Number(right.percentage) - Number(left.percentage) ||
        left.label.localeCompare(right.label),
    ), [summary],
  );
  const assetsByAllocation = useMemo(
    () => [...(summary?.by_asset_type ?? [])].sort(
      (left, right) => Number(right.percentage) - Number(left.percentage) ||
        left.label.localeCompare(right.label),
    ), [summary],
  );
  return (
    <>
      <header className="page-header">
        <div><p className="eyebrow">Portfolio overview</p><h1>Your financial picture</h1></div>
        <span className="as-of">Values displayed in EUR</span>
      </header>
      {error && <p className="error">{error}</p>}
      <section className="metric-grid">
        <article className="metric primary-metric">
          <span>Total portfolio</span>
          <strong>{summary ? money.format(Number(summary.total_value_eur)) : "—"}</strong>
          <small>Across all connected sources</small>
        </article>
        <article className="metric">
          <span>Positions</span>
          <strong>{summary?.positions_count ?? "—"}</strong>
          <small><Link to="/holdings">View all holdings</Link></small>
        </article>
        <article className="metric">
          <span>Connected sources</span>
          <strong>{summary?.by_source.length ?? "—"}</strong>
          <small><Link to="/connections">Manage sources</Link></small>
        </article>
      </section>

      <section className="allocation-visual-grid">
        <article className="panel allocation-visual-panel">
          <div className="panel-heading"><div><p className="eyebrow">Allocation</p><h2>By source</h2></div></div>
          {sourcesByAllocation.length && summary ? (
            <SourceDonut items={sourcesByAllocation} total={Number(summary.total_value_eur)} />
          ) : <EmptyState title="Connect your first account">Your aggregated portfolio will appear here after its first sync. <Link to="/connections">Add a connection</Link></EmptyState>}
        </article>
        <article className="panel allocation-visual-panel">
          <div className="panel-heading"><div><p className="eyebrow">Asset mix</p><h2>Where you are invested</h2></div></div>
          {assetsByAllocation.length ? <AssetAllocation items={assetsByAllocation} /> : (
            <EmptyState title="No asset allocation">Synchronize a source to build your asset mix.</EmptyState>
          )}
        </article>
      </section>

      <section className="dashboard-grid overview-secondary-grid">
        <article className="panel"><p className="eyebrow">AI insight</p><h2>Portfolio review</h2><p className="muted">Enable the OpenAI feature flag to generate cached observations based on your holdings and risk profile.</p><div className="disclaimer">Informational and educational only—not financial advice.</div></article>
        <article className="panel"><p className="eyebrow">Market pulse</p><h2>Relevant news</h2><p className="muted">Holding-specific news and earnings dates will appear after market news is enabled.</p></article>
      </section>
    </>
  );
}
