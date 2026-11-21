import { useEffect, useMemo, useState } from "react";
import { api, cachedApi } from "../../api/client";
import { loadFeatures } from "../../api/features";
import type {
  AllocationItem,
  ContentSummary,
  DashboardSummary,
  FeatureStatus,
  HoldingsResponse,
  PortfolioReview,
  PortfolioHistoryPoint,
  PortfolioPerformance,
} from "../../api/types";
import { EmptyState } from "../../components/EmptyState";
import { Loading } from "../../components/Loading";
import { CsvDownloadButton } from "../../components/CsvDownloadButton";
import { brokerNameFromValue } from "../../domain/brokers";
import { formatEur } from "../../lib/format";
import { Link } from "../../routing/Router";
import { GettingStarted } from "./GettingStarted";
import { OverviewMetrics, TopMovers } from "./OverviewMetrics";

const assetLabels: Record<string, string> = {
  stock: "Stocks",
  etf: "ETFs",
  crypto: "Crypto",
  cash: "Cash",
  other: "Other",
};
const allocationColors = ["#83e5b5", "#70a8f7", "#f1ba52", "#c19bf5", "#ed8f88"];
const compactMoney = new Intl.NumberFormat("en-IE", {
  style: "currency", currency: "EUR", notation: "compact", maximumFractionDigits: 1,
});
const historyDate = new Intl.DateTimeFormat("en-IE", {
  day: "numeric", month: "short", year: "numeric", timeZone: "UTC",
});
const rangeOptions: Array<{ value: PortfolioPerformance["range"]; label: string }> = [
  { value: "1w", label: "1W" },
  { value: "1m", label: "1M" },
  { value: "3m", label: "3M" },
  { value: "6m", label: "6M" },
  { value: "1y", label: "1Y" },
  { value: "5y", label: "5Y" },
  { value: "all", label: "All" },
];
const millisecondsPerDay = 86_400_000;

function formatHistoryDate(value: string) {
  return historyDate.format(new Date(`${value}T00:00:00Z`));
}

function samplingLabel(performance: PortfolioPerformance) {
  const labels = {
    daily: "Daily values",
    weekly_average: "Weekly averages",
    monthly_average: "Monthly averages",
    adaptive_average: "Averaged to fit",
  } as const;
  const method = performance.history_method === "reconstructed"
    ? "Estimated from your trade history (weekly)"
    : labels[performance.sampling];
  return `${method} · ${performance.points.length} points`;
}

function PortfolioValueFigure({
  points,
  windowStart,
  windowEnd,
}: {
  points: PortfolioHistoryPoint[];
  windowStart: string;
  windowEnd: string;
}) {
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);
  const width = 900;
  const height = 260;
  const margin = { top: 18, right: 18, bottom: 36, left: 72 };
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;
  const values = points.flatMap((point) => [
    Number(point.total_value_eur),
    Number(point.invested_value_eur),
  ]);
  const minimum = Math.min(...values);
  const maximum = Math.max(...values);
  const naturalSpread = maximum - minimum;
  const padding = naturalSpread > 0
    ? naturalSpread * 0.12
    : Math.max(Math.abs(maximum) * 0.02, 1);
  const yMinimum = Math.max(0, minimum - padding);
  const yMaximum = maximum + padding;
  const ySpread = Math.max(yMaximum - yMinimum, 1);
  const windowStartTime = Date.parse(`${windowStart}T00:00:00Z`);
  const windowEndTime = Date.parse(`${windowEnd}T00:00:00Z`);
  const windowDuration = Math.max(windowEndTime - windowStartTime, millisecondsPerDay);
  const xForDate = (value: string) => {
    const timestamp = Date.parse(`${value}T00:00:00Z`);
    return margin.left + ((timestamp - windowStartTime) / windowDuration) * plotWidth;
  };
  const yFor = (value: number) => margin.top + ((yMaximum - value) / ySpread) * plotHeight;
  const pathFor = (field: "total_value_eur" | "invested_value_eur") => points.map((point, index) => {
    const command = index === 0 ? "M" : "L";
    return `${command}${xForDate(point.date).toFixed(2)},${yFor(Number(point[field])).toFixed(2)}`;
  }).join(" ");
  const yTicks = Array.from({ length: 4 }, (_, index) => {
    const ratio = index / 3;
    return { value: yMaximum - ySpread * ratio, y: margin.top + plotHeight * ratio };
  });
  const xTicks = Array.from({ length: 5 }, (_, index) => {
    const timestamp = windowStartTime + (windowDuration * index) / 4;
    return new Date(timestamp).toISOString().slice(0, 10);
  });
  const activeIndex = hoveredIndex ?? points.length - 1;
  const activePoint = points[activeIndex];

  return (
    <div className="portfolio-history-figure">
      <div className="history-chart-readout" aria-live="polite">
        <span className="history-readout-date">{formatHistoryDate(activePoint.date)}</span>
        <span className="history-readout-value total-value">
          <i /> <small>Total value</small>
          <strong>{formatEur(Number(activePoint.total_value_eur))}</strong>
        </span>
        <span className="history-readout-value invested-amount">
          <i /> <small>Invested amount</small>
          <strong>{formatEur(Number(activePoint.invested_value_eur))}</strong>
        </span>
      </div>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label={`Total portfolio value and invested amount from ${formatHistoryDate(windowStart)} to ${formatHistoryDate(windowEnd)}`}
        onPointerLeave={() => setHoveredIndex(null)}
      >
        {yTicks.map((tick) => (
          <g key={tick.y}>
            <line className="history-grid-line" x1={margin.left} x2={width - margin.right} y1={tick.y} y2={tick.y} />
            <text className="history-axis-label history-y-label" x={margin.left - 12} y={tick.y + 4}>{compactMoney.format(tick.value)}</text>
          </g>
        ))}
        {xTicks.map((tick, index) => (
          <text
            className="history-axis-label"
            key={`${tick}-${index}`}
            x={margin.left + (plotWidth * index) / 4}
            y={height - 8}
            textAnchor={index === 0 ? "start" : index === 4 ? "end" : "middle"}
          >
            {formatHistoryDate(tick)}
          </text>
        ))}
        <path className="history-value-line invested-amount" d={pathFor("invested_value_eur")} />
        <path className="history-value-line total-value" d={pathFor("total_value_eur")} />
        {points.map((point, index) => (
          <circle
            className="history-point-target"
            key={`${point.date}-${index}`}
            cx={xForDate(point.date)}
            cy={yFor(Number(point.total_value_eur))}
            r={Math.max(8, Math.min(16, plotWidth / points.length / 2))}
            onPointerEnter={() => setHoveredIndex(index)}
            onPointerDown={() => setHoveredIndex(index)}
          />
        ))}
        {hoveredIndex !== null && (
          <line className="history-hover-line" x1={xForDate(activePoint.date)} x2={xForDate(activePoint.date)} y1={margin.top} y2={margin.top + plotHeight} />
        )}
        <circle className="history-active-point invested-amount" cx={xForDate(activePoint.date)} cy={yFor(Number(activePoint.invested_value_eur))} r="4" />
        <circle className="history-active-point total-value" cx={xForDate(activePoint.date)} cy={yFor(Number(activePoint.total_value_eur))} r="5" />
      </svg>
    </div>
  );
}

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
        <span className="donut-center"><small>Total</small><strong>{formatEur(total)}</strong></span>
      </div>
      <div className="allocation-legend">
        {items.map((item, index) => (
          <div key={item.label}>
            <i style={{ backgroundColor: allocationColors[index % allocationColors.length] }} />
            <span>{brokerNameFromValue(item.label)}</span>
            <strong>{item.percentage}%</strong>
            <small>{formatEur(Number(item.value_eur))}</small>
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
          <small>{formatEur(Number(item.value_eur))}</small>
        </div>
      ))}
    </div>
  );
}

export function DashboardPage() {
  const [summary, setSummary] = useState(() => cachedApi<DashboardSummary>("/dashboard/summary"));
  const [error, setError] = useState("");
  const [selectedRange, setSelectedRange] = useState<PortfolioPerformance["range"]>("1y");
  const [holdings, setHoldings] = useState(() => cachedApi<HoldingsResponse>("/holdings"));
  const [performance, setPerformance] = useState(() => cachedApi<PortfolioPerformance>("/performance?range=1y"));
  const [performanceError, setPerformanceError] = useState("");
  const [performanceLoading, setPerformanceLoading] = useState(true);
  const [content, setContent] = useState(() =>
    cachedApi<ContentSummary>("/content?news_limit=3&event_limit=3&alert_limit=3"));
  const [features, setFeatures] = useState<FeatureStatus | null>(null);
  const [review, setReview] = useState<PortfolioReview | null>(null);
  useEffect(() => {
    api<DashboardSummary>("/dashboard/summary")
      .then(setSummary).catch((reason: Error) => setError(reason.message));
    api<HoldingsResponse>("/holdings").then(setHoldings).catch(() => undefined);
    api<ContentSummary>("/content?news_limit=3&event_limit=3&alert_limit=3")
      .then(setContent).catch(() => undefined);
    loadFeatures().then((status) => {
      setFeatures(status);
      if (status.ai) api<PortfolioReview | null>("/assistant/review").then(setReview).catch(() => undefined);
    }).catch(() => undefined);
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    // Keep the current chart on screen (dimmed) while the new period loads.
    setPerformanceLoading(true);
    setPerformanceError("");
    api<PortfolioPerformance>(`/performance?range=${selectedRange}`, { signal: controller.signal })
      .then((result) => {
        setPerformance(result);
      })
      .catch((reason: Error) => {
        if (reason.name !== "AbortError") setPerformanceError(reason.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setPerformanceLoading(false);
      });
    return () => controller.abort();
  }, [selectedRange]);
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
  const isEmpty = summary !== null && summary.positions_count === 0 && summary.by_source.length === 0;
  const showUpdates = Boolean(features?.news || content?.alerts.length);
  if (isEmpty) {
    return (
      <>
        <header className="page-header">
          <div><p className="eyebrow">Welcome</p><h1>Your financial picture</h1></div>
        </header>
        <GettingStarted />
      </>
    );
  }
  return (
    <>
      <header className="page-header">
        <div><p className="eyebrow">Portfolio overview</p><h1>Your financial picture</h1></div>
        <span className="as-of">Values displayed in EUR</span>
      </header>
      {error && <p className="error">{error}</p>}
      <OverviewMetrics
        totalValue={summary ? Number(summary.total_value_eur) : null}
        holdings={holdings}
        performance={performance?.range === selectedRange ? performance : null}
        performanceFailed={Boolean(performanceError)}
        range={selectedRange}
      />

      <section
        className={`panel portfolio-history-panel${performanceLoading && performance ? " is-updating" : ""}`}
        aria-busy={performanceLoading}
      >
        <div className="portfolio-history-heading">
          <div>
            <p className="eyebrow">Portfolio history</p>
            <h2>Value and invested amount</h2>
          </div>
          <div className="portfolio-history-actions">
            {performanceLoading && performance && (
              <span className="loading-spinner" role="status" aria-label="Updating" />
            )}
            <CsvDownloadButton
              path={`/exports/performance.csv?range=${selectedRange}`}
              disabled={!performance}
            />
            <div className="history-range-picker" aria-label="Portfolio history range">
              {rangeOptions.map((option) => (
                <button
                  className={selectedRange === option.value ? "active" : ""}
                  key={option.value}
                  type="button"
                  aria-pressed={selectedRange === option.value}
                  onClick={() => setSelectedRange(option.value)}
                >
                  {option.label}
                </button>
              ))}
            </div>
          </div>
        </div>
        {performanceError && <p className="history-message error">{performanceError}</p>}
        {performanceLoading && !performance && <Loading className="history-loading" label="Loading history…" />}
        {!performanceLoading && performance && performance.points.length === 0 && (
          <EmptyState title="History starts with your first sync">Once daily values are available, they will appear here.</EmptyState>
        )}
        {performance && performance.points.length > 0 && (
          <>
            <PortfolioValueFigure
              key={performance.range}
              points={performance.points}
              windowStart={performance.start_date ?? performance.points[0].date}
              windowEnd={performance.end_date ?? performance.points.at(-1)?.date ?? performance.points[0].date}
            />
            <div className="history-chart-meta">
              <span>{samplingLabel(performance)}</span>
              {performance.start_date && performance.end_date && (
                <span>Data available: {formatHistoryDate(performance.start_date)} – {formatHistoryDate(performance.end_date)}</span>
              )}
            </div>
          </>
        )}
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
        <TopMovers holdings={holdings} />
        {features?.ai && <article className="panel dashboard-brief-card">
          <div className="panel-heading"><div><p className="eyebrow">AI insight</p><h2>Portfolio review</h2></div><Link to="/assistant">Open</Link></div>
          {review ? <><p className="brief-copy">{review.content.split("\n").find(Boolean)}</p><small>Generated {new Date(review.generated_at).toLocaleDateString()}</small></>
            : <p className="muted">Generate a review from your calculated analytics.</p>}
          <div className="disclaimer">Informational and educational only—not financial advice.</div>
        </article>}
        {showUpdates && <article className="panel dashboard-brief-card">
          <div className="panel-heading"><div><p className="eyebrow">Updates</p><h2>{features?.news ? "News and calendar" : "Alerts"}</h2></div><Link to="/updates">View all</Link></div>
          {content?.alerts.some((item) => !item.read_at) && <div className="dashboard-alert-line"><i />{content.unread_alerts} item{content.unread_alerts === 1 ? "" : "s"} need attention</div>}
          {content?.news.length ? <div className="dashboard-news-list">{content.news.slice(0, 2).map((item) => <a href={item.url} target="_blank" rel="noreferrer" key={item.id}><span>{item.ticker}</span><strong>{item.headline}</strong></a>)}</div>
            : features?.news ? <p className="muted">Relevant held-company news will appear here.</p> : null}
          {content?.events[0] && <small>Next: {content.events[0].title} · {new Date(`${content.events[0].event_date}T12:00:00`).toLocaleDateString()}</small>}
        </article>}
      </section>
    </>
  );
}
