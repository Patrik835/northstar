import type { Holding, HoldingsResponse, PortfolioPerformance } from "../../api/types";
import { formatChange, formatEur, formatPercentChange, tone } from "../../lib/format";
import { Skeleton } from "../../components/Loading";
import { Link } from "../../routing/Router";
import { summarizePnl, type PnlSummary } from "../holdings/holdingMath";

export const rangeLabels: Record<PortfolioPerformance["range"], string> = {
  "1w": "in the last 7 days",
  "1m": "in the last 30 days",
  "3m": "in the last 3 months",
  "6m": "in the last 6 months",
  ytd: "this year",
  "1y": "in the last 12 months",
  "5y": "in the last 5 years",
  all: "since you started",
};

function ChangeValue({ value, percentage }: { value: number; percentage: number | null }) {
  return (
    <strong className={tone(value)}>
      {formatChange(value)}
      {percentage !== null && <small> {formatPercentChange(percentage)}</small>}
    </strong>
  );
}

/** The three numbers that answer "how am I doing?". */
export function OverviewMetrics({
  totalValue,
  holdings,
  performance,
  performanceFailed = false,
  range,
}: {
  totalValue: number | null;
  holdings: HoldingsResponse | null;
  performance: PortfolioPerformance | null;
  performanceFailed?: boolean;
  range: PortfolioPerformance["range"];
}) {
  const pnl = holdings ? summarizePnl(holdings.holdings.flatMap((holding) => holding.sources)) : null;
  const partial = pnl !== null && pnl.sourceCount < pnl.totalSources;
  const attribution = performance?.attribution;
  const periodReturn = attribution?.total_return_eur;
  // Simple return: the € change divided by the money at work (start value + money added),
  // so the € and % on this card always agree.
  const periodPercent = attribution?.simple_return_percentage;
  const startValue = Number(attribution?.start_value_eur ?? 0);
  const added = Number(attribution?.net_contributions_eur ?? 0);
  const hasPeriod = periodReturn != null && attribution?.status !== "unavailable";
  const missingHistory = (performance?.missing_fx_transaction_count ?? 0) > 0;

  return (
    <section className="metric-grid">
      <article className="metric primary-metric">
        <span>Total value</span>
        <strong>{totalValue === null ? <Skeleton width="9rem" /> : formatEur(totalValue)}</strong>
        <small><Link to="/holdings">See all investments</Link></small>
      </article>
      <article className="metric">
        <span>Gain / loss</span>
        {pnl ? <ChangeValue value={pnl.value} percentage={pnl.percentage} />
          : <strong>{holdings ? "—" : <Skeleton />}</strong>}
        <small>
          {!holdings
            ? <Skeleton width="10rem" />
            : !pnl
              ? "Add what you paid to see your gain"
              : partial
                ? `On ${formatEur(pnl.costBasis)} paid for ${pnl.sourceCount} of ${pnl.totalSources} positions (the rest have no known price)`
                : `On ${formatEur(pnl.costBasis)} you paid`}
        </small>
      </article>
      <article className="metric">
        <span>Change {rangeLabels[range]}</span>
        {hasPeriod ? (
          <ChangeValue
            value={Number(periodReturn)}
            percentage={periodPercent != null ? Number(periodPercent) : null}
          />
        ) : <strong>{performance || performanceFailed ? "—" : <Skeleton />}</strong>}
        <small>
          {performanceFailed && !performance
            ? "Couldn't load this period. Try another one."
            : !performance
            ? <Skeleton width="10rem" />
            : !hasPeriod
              ? "Not enough history for this period yet"
              : `On ${formatEur(startValue)} at the start${added > 0 ? ` + ${formatEur(added)} added` : ""} · deposits don't count as gain${missingHistory ? " · estimate, some history is missing" : ""}`}
        </small>
      </article>
    </section>
  );
}

type Mover = { holding: Holding; pnl: PnlSummary };

/** The few holdings that moved the most, so users see what is driving the result. */
export function TopMovers({ holdings }: { holdings: HoldingsResponse | null }) {
  const movers: Mover[] = (holdings?.holdings ?? [])
    .flatMap((holding) => {
      const pnl = summarizePnl(holding.sources);
      return pnl && pnl.value !== 0 ? [{ holding, pnl }] : [];
    })
    .sort((left, right) => Math.abs(right.pnl.value) - Math.abs(left.pnl.value))
    .slice(0, 4);

  return (
    <article className="panel dashboard-brief-card top-movers">
      <div className="panel-heading">
        <div><p className="eyebrow">Top movers</p><h2>Biggest gains and losses</h2></div>
        <Link to="/holdings">All investments</Link>
      </div>
      {movers.length ? (
        <ul className="mover-list">
          {movers.map(({ holding, pnl }) => (
            <li key={holding.key}>
              <span className="mover-name">
                <strong>{holding.name}</strong>
                <small>{holding.symbol} · {formatEur(Number(holding.total_value_eur))}</small>
              </span>
              <span className={`mover-change ${tone(pnl.value)}`}>
                {formatChange(pnl.value)}
                {pnl.percentage !== null && <small>{formatPercentChange(pnl.percentage)}</small>}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="muted">Gains and losses appear once your sources report what you paid.</p>
      )}
    </article>
  );
}
