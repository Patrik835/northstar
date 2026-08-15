import { useEffect, useMemo, useState } from "react";
import { api } from "../../api/client";
import type {
  AllocationBreakdown,
  AnalyticsPerformer,
  AnalyticsResponse,
  PortfolioPerformance,
} from "../../api/types";
import { EmptyState } from "../../components/EmptyState";

const money = new Intl.NumberFormat("en-IE", {
  style: "currency", currency: "EUR", maximumFractionDigits: 2,
});
const percent = new Intl.NumberFormat("en-IE", { maximumFractionDigits: 2 });
const rangeOptions: Array<{ value: PortfolioPerformance["range"]; label: string }> = [
  { value: "3m", label: "3M" }, { value: "6m", label: "6M" },
  { value: "1y", label: "1Y" }, { value: "5y", label: "5Y" },
  { value: "all", label: "All" },
];
const rangeDescriptions: Record<PortfolioPerformance["range"], string> = {
  "1w": "Last week",
  "1m": "Last month",
  "3m": "Last 3 months",
  "6m": "Last 6 months",
  "1y": "Last 1 year",
  "5y": "Last 5 years",
  all: "All available history",
};
const dimensionLabels: Record<AllocationBreakdown["dimension"], string> = {
  asset_type: "Asset type", holding: "Holding", broker: "Broker",
  currency: "Currency", sector: "Sector", geography: "Geography",
};
const valueLabels: Record<string, string> = {
  stock: "Stocks", etf: "ETFs", crypto: "Crypto", cash: "Cash", other: "Other",
  trading212: "Trading 212", trading212_crypto: "Trading 212 Crypto",
  etoro: "eToro", binance: "Binance", xtb: "XTB",
};

function signed(value: number, suffix = "%") {
  return `${value > 0 ? "+" : ""}${percent.format(value)}${suffix}`;
}

function tone(value: number) {
  return value > 0 ? "positive" : value < 0 ? "negative" : "";
}

function Coverage({ status, coverage }: { status: string; coverage?: string }) {
  return (
    <span className={`analytics-coverage ${status}`}>
      {coverage ? `${percent.format(Number(coverage))}% covered` : status}
    </span>
  );
}

function AllocationBars({ breakdown }: { breakdown: AllocationBreakdown }) {
  return (
    <div className="analytics-allocation-content">
      <div className="analytics-section-meta">
        <Coverage status={breakdown.status} coverage={breakdown.coverage_percentage} />
        {breakdown.message && <span>{breakdown.message}</span>}
      </div>
      <div className="analytics-bars">
        {breakdown.items.slice(0, breakdown.dimension === "holding" ? 15 : 12).map((item) => (
          <div className="analytics-bar-row" key={item.label}>
            <span title={item.label}>{valueLabels[item.label] ?? item.label}</span>
            <strong>{item.percentage}%</strong>
            <div><i style={{ width: `${Math.min(Number(item.percentage), 100)}%` }} /></div>
            <small>{money.format(Number(item.value_eur))}</small>
          </div>
        ))}
      </div>
    </div>
  );
}

function PerformerList({ items, empty }: { items: AnalyticsPerformer[]; empty: string }) {
  if (!items.length) return <p className="muted analytics-empty-copy">{empty}</p>;
  return (
    <div className="performer-list">
      {items.map((item) => (
        <div key={item.holding_key}>
          <span><strong>{item.symbol}</strong><small>{item.name}</small></span>
          <span className={tone(Number(item.open_pnl_percentage))}>
            <strong>{signed(Number(item.open_pnl_percentage))}</strong>
            <small>{money.format(Number(item.open_pnl_eur))}</small>
          </span>
        </div>
      ))}
    </div>
  );
}

function ContributionBars({ items }: { items: AnalyticsPerformer[] }) {
  const maximum = Math.max(...items.map((item) => Math.abs(Number(item.contribution_percentage_points))), 1);
  return (
    <div className="contribution-list">
      {items.map((item) => {
        const value = Number(item.contribution_percentage_points);
        return (
          <div key={item.holding_key}>
            <span>{item.symbol}</span>
            <div className={value < 0 ? "negative" : "positive"}>
              <i style={{ width: `${Math.abs(value) / maximum * 100}%` }} />
            </div>
            <strong className={tone(value)}>{signed(value, " pp")}</strong>
          </div>
        );
      })}
    </div>
  );
}

function ReturnFigure({ data }: { data: AnalyticsResponse["benchmark"] }) {
  const width = 760;
  const height = 230;
  const margin = { top: 16, right: 14, bottom: 28, left: 48 };
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;
  const values = data.points.flatMap((item) => [
    Number(item.portfolio_return_percentage), Number(item.benchmark_return_percentage),
  ]);
  const minimum = Math.min(...values, 0);
  const maximum = Math.max(...values, 0);
  const spread = Math.max(maximum - minimum, 1);
  const x = (index: number) => margin.left + index / Math.max(data.points.length - 1, 1) * plotWidth;
  const y = (value: number) => margin.top + (maximum - value) / spread * plotHeight;
  const path = (field: "portfolio_return_percentage" | "benchmark_return_percentage") =>
    data.points.map((item, index) => `${index ? "L" : "M"}${x(index)},${y(Number(item[field]))}`).join(" ");
  return (
    <div className="benchmark-figure">
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Portfolio and benchmark return comparison">
        <line className="benchmark-zero" x1={margin.left} x2={width - margin.right} y1={y(0)} y2={y(0)} />
        <path className="benchmark-line portfolio" d={path("portfolio_return_percentage")} />
        <path className="benchmark-line proxy" d={path("benchmark_return_percentage")} />
      </svg>
      <div className="benchmark-legend">
        <span><i className="portfolio" />Portfolio <strong>{signed(Number(data.portfolio_return_percentage))}</strong></span>
        <span><i className="proxy" />{data.selected_symbol} <strong>{signed(Number(data.benchmark_return_percentage))}</strong></span>
      </div>
    </div>
  );
}

export function AnalyticsPage() {
  const [selectedRange, setSelectedRange] = useState<PortfolioPerformance["range"]>("1y");
  const [data, setData] = useState<AnalyticsResponse | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [refreshToken, setRefreshToken] = useState(0);
  const [dimension, setDimension] = useState<AllocationBreakdown["dimension"]>("holding");
  const [targetDrafts, setTargetDrafts] = useState<Record<string, string>>({});
  const [savingTargets, setSavingTargets] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");
    api<AnalyticsResponse>(`/analytics?range=${selectedRange}`, { signal: controller.signal })
      .then(setData)
      .catch((reason: Error) => {
        if (reason.name !== "AbortError") setError(reason.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [selectedRange, refreshToken]);

  useEffect(() => {
    if (!data) return;
    setTargetDrafts(Object.fromEntries(data.targets.items.map((item) => [
      item.holding_key, item.target_percentage ?? "",
    ])));
  }, [data]);

  const activeAllocation = data?.allocations.find((item) => item.dimension === dimension);
  const targetTotal = useMemo(() => Object.values(targetDrafts).reduce(
    (sum, raw) => sum + (raw.trim() ? Number(raw) : 0), 0,
  ), [targetDrafts]);

  async function saveBenchmark(instrumentId: string) {
    try {
      setError("");
      await api<AnalyticsResponse>("/analytics/benchmark", {
        method: "PUT", body: JSON.stringify({ instrument_id: instrumentId || null }),
      });
      setRefreshToken((value) => value + 1);
    } catch (reason) {
      setError((reason as Error).message);
    }
  }

  async function saveTargets() {
    if (!data || targetTotal > 100) return;
    setSavingTargets(true);
    try {
      await api<AnalyticsResponse>("/analytics/targets", {
        method: "PUT",
        body: JSON.stringify({ items: data.targets.items.map((item) => ({
          holding_key: item.holding_key,
          target_percentage: targetDrafts[item.holding_key]?.trim()
            ? Number(targetDrafts[item.holding_key]) : null,
        })) }),
      });
      setRefreshToken((value) => value + 1);
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setSavingTargets(false);
    }
  }

  return (
    <>
      <header className="page-header analytics-page-header">
        <div><p className="eyebrow">Portfolio analytics</p><h1>Understand what drives your wealth</h1></div>
        <div className="history-range-picker" aria-label="Analytics history range">
          {rangeOptions.map((option) => (
            <button
              type="button" key={option.value}
              className={selectedRange === option.value ? "active" : ""}
              aria-pressed={selectedRange === option.value}
              onClick={() => setSelectedRange(option.value)}
            >{option.label}</button>
          ))}
        </div>
      </header>
      {error && <p className="error">{error}</p>}
      {loading && !data && <section className="panel analytics-loading">Calculating portfolio analytics…</section>}
      {data && (
        <>
          <section className="analytics-risk-grid">
            <article><span>Maximum drawdown</span><strong>{data.risk.maximum_drawdown_percentage === null ? "—" : `−${percent.format(Number(data.risk.maximum_drawdown_percentage))}%`}</strong><small>{data.risk.observation_count} observations</small></article>
            <article><span>Annualized volatility</span><strong>{data.risk.annualized_volatility_percentage === null ? "—" : `${percent.format(Number(data.risk.annualized_volatility_percentage))}%`}</strong><small>Cash-flow adjusted</small></article>
            <article><span>Largest holding</span><strong>{percent.format(Number(data.risk.largest_holding_percentage))}%</strong><small>Top five {percent.format(Number(data.risk.top_five_percentage))}%</small></article>
            <article><span>Diversification</span><strong>{percent.format(Number(data.risk.diversification_score))}/100</strong><small>{data.risk.effective_holdings} effective holdings</small></article>
          </section>
          <p className="analytics-method-note"><Coverage status={data.risk.status} />{data.risk.message}</p>

          <section className="panel analytics-allocation-panel">
            <div className="panel-heading"><div><p className="eyebrow">Allocation</p><h2>Portfolio composition</h2></div></div>
            <div className="analytics-tabs" role="tablist" aria-label="Allocation dimension">
              {data.allocations.map((item) => (
                <button type="button" role="tab" key={item.dimension}
                  aria-selected={dimension === item.dimension}
                  className={dimension === item.dimension ? "active" : ""}
                  onClick={() => setDimension(item.dimension)}>
                  {dimensionLabels[item.dimension]}
                </button>
              ))}
            </div>
            {activeAllocation && <AllocationBars breakdown={activeAllocation} />}
          </section>

          <section className="analytics-two-column">
            <article className="panel">
              <div className="panel-heading"><div><p className="eyebrow">Open performance</p><h2>Best and worst holdings</h2></div><Coverage status="available" coverage={data.performance.coverage_percentage} /></div>
              <div className="leader-columns">
                <div><h3>Best</h3><PerformerList items={data.performance.best} empty="No covered gains yet." /></div>
                <div><h3>Worst</h3><PerformerList items={data.performance.worst} empty="No covered losses yet." /></div>
              </div>
              <p className="analytics-caption">{data.performance.message}</p>
            </article>
            <article className="panel">
              <div className="panel-heading"><div><p className="eyebrow">Contribution</p><h2>Impact on portfolio</h2></div></div>
              {data.performance.contributors.length
                ? <ContributionBars items={data.performance.contributors} />
                : <EmptyState title="No P/L coverage">Synchronize provider-reported P/L to calculate contribution.</EmptyState>}
            </article>
          </section>

          <section className="panel analytics-benchmark-panel">
            <div className="panel-heading">
              <div>
                <p className="eyebrow">Benchmark</p>
                <h2>Portfolio versus an investable ETF</h2>
                <p className="analytics-panel-period">{rangeDescriptions[data.range]}</p>
              </div>
              <label className="benchmark-select">Compare with<select value={data.benchmark.selected_instrument_id ?? ""} onChange={(event) => void saveBenchmark(event.target.value)}>
                {data.benchmark.options.map((option) => <option value={option.instrument_id} key={option.instrument_id}>{option.symbol} · {option.name}</option>)}
              </select></label>
            </div>
            {data.benchmark.points.length > 1 ? <ReturnFigure data={data.benchmark} /> : (
              <EmptyState title="Benchmark history unavailable">A cached ETF with overlapping history is needed.</EmptyState>
            )}
            <p className="analytics-caption"><Coverage status={data.benchmark.status} />{data.benchmark.message}</p>
          </section>

          <section className="panel analytics-target-panel">
            <div className="panel-heading">
              <div><p className="eyebrow">Target allocation</p><h2>Drift and rebalancing illustration</h2></div>
              <div className={`target-total ${targetTotal > 100 ? "negative" : ""}`}>{percent.format(targetTotal)}% assigned</div>
            </div>
            <div className="target-table">
              <div className="target-table-head"><span>Holding</span><span>Current</span><span>Target</span><span>Drift</span><span>Illustration</span></div>
              {data.targets.items.map((item) => {
                const draft = targetDrafts[item.holding_key] ?? "";
                const target = draft.trim() ? Number(draft) : null;
                const drift = target === null ? null : Number(item.current_percentage) - target;
                const difference = target === null ? null : Number(data.allocations[0]?.scope_value_eur ?? 0) * target / 100 - Number(item.current_value_eur);
                return (
                  <div className="target-table-row" key={item.holding_key}>
                    <span><strong>{item.symbol}</strong><small>{item.name}</small></span>
                    <span>{item.current_percentage}%</span>
                    <label><input type="number" min="0" max="100" step="0.1" value={draft} placeholder="—" aria-label={`${item.symbol} target percentage`} onChange={(event) => setTargetDrafts((current) => ({ ...current, [item.holding_key]: event.target.value }))} /><small>%</small></label>
                    <span className={drift === null ? "muted" : tone(-drift)}>{drift === null ? "Not set" : signed(drift, " pp")}</span>
                    <span className={difference === null ? "muted" : tone(difference)}>{difference === null ? "—" : `${difference > 0 ? "Add " : "Reduce "}${money.format(Math.abs(difference))}`}</span>
                  </div>
                );
              })}
            </div>
            <div className="target-actions"><p>{data.targets.message}</p><button type="button" disabled={savingTargets || targetTotal > 100} onClick={() => void saveTargets()}>{savingTargets ? "Saving…" : "Save targets"}</button></div>
          </section>
        </>
      )}
    </>
  );
}
