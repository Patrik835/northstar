import { useEffect, useState } from "react";
import { api } from "../../api/client";
import type {
  ActivityResponse,
  AssetType,
  Holding,
  HoldingSource,
} from "../../api/types";
import { activityLabels } from "../../domain/activity";
import { brokerName } from "../../domain/brokers";
import { Link } from "../../routing/Router";
import { eur, quantity, sourceValue, sourceQuantity, originalMoney, timestamp, valuationLabel, preferredSourcePnl, signedMoney, signedPercentage, type PnlSummary } from "./holdingMath";

export function PnlLine({
  summary,
  unavailable = false,
  label = "Gain/loss",
}: {
  summary: PnlSummary | null;
  unavailable?: boolean;
  label?: string;
}) {
  if (!summary) {
    return unavailable ? <span className="pnl-summary unavailable">Gain/loss unknown</span> : null;
  }
  const tone =
    summary.value > 0 ? "positive" : summary.value < 0 ? "negative" : "neutral";
  const partial = summary.sourceCount < summary.totalSources;
  return (
    <span
      className={`pnl-summary ${tone}`}
      title={summary.calculatedCount
        ? "Calculated from your imported trades; the broker's own figure is used where trade history is incomplete"
        : "Compared with what you paid, from your purchase prices or the broker's report"}
    >
      <span>{label ? `${label} ` : ""}{signedMoney(summary.value)}</span>
      {summary.percentage !== null && <span>{signedPercentage(summary.percentage)}</span>}
      {partial && (
        <em title={`Known for ${summary.sourceCount} of ${summary.totalSources} positions; the rest have no price paid`}>
          partial
        </em>
      )}
    </span>
  );
}

export function SourcePnlMetric({ source }: { source: HoldingSource }) {
  const pnl = preferredSourcePnl(source);
  if (!pnl) {
    return (
      <div>
        <dt>Gain/loss</dt>
        <dd className="unavailable">Not available</dd>
      </div>
    );
  }

  const costBasis = sourceValue(source) - pnl.valueEur;
  const pnlPercentage = costBasis > 0 ? (pnl.valueEur * 100) / costBasis : null;
  const secondary = [
    pnl.kind === "reported" && source.currency !== "EUR"
      ? signedMoney(pnl.valueEur)
      : null,
    pnlPercentage !== null ? signedPercentage(pnlPercentage) : null,
  ].filter(Boolean).join(" · ");

  return (
    <div>
      <dt>Gain/loss</dt>
      <dd className={`pnl-source-value ${pnl.valueEur >= 0 ? "positive" : "negative"}`}>
        <span>
          {pnl.kind === "reported" && source.reported_pnl !== null
            ? originalMoney(source.reported_pnl, source.currency)
            : signedMoney(pnl.valueEur)}
        </span>
        {secondary && <small>{secondary}</small>}
        <small>
          {pnl.kind === "manual"
            ? source.valuation_source === "market"
              ? "Calculated from latest market price" : "Calculated from your manual prices"
            : pnl.kind === "calculated"
              ? "Calculated from your trades"
              : "Reported by the broker"}
        </small>
      </dd>
    </div>
  );
}

export type ScopedHolding = Holding & {
  totalValue: number;
  totalQuantity: number | null;
  pnl: PnlSummary | null;
};

export function performanceTone(value: number) {
  return value > 0 ? "positive" : value < 0 ? "negative" : "neutral";
}

export function HoldingPerformanceSummary({ holding }: { holding: ScopedHolding }) {
  const performance = holding.performance;
  const income = Number(performance.income_eur);
  const fees = Number(performance.fees_eur);
  const hasImportedResults = performance.coverage !== "unavailable" || income !== 0 || fees !== 0;
  if (!hasImportedResults) return null;

  const realized = performance.realized_pnl_eur === null
    ? null
    : Number(performance.realized_pnl_eur);
  const totalReturn = performance.total_return_eur === null
    ? null
    : Number(performance.total_return_eur);
  return (
    <section className="holding-performance-strip" aria-label="Results over time">
      <div className="performance-strip-heading">
        <span>Results over time</span>
        <small>
          {performance.coverage === "complete"
            ? "Full trade history"
            : "Some trade history is missing · totals we can't confirm are hidden"}
        </small>
      </div>
      <div>
        <small>Profit from sales</small>
        <strong className={realized === null ? "unavailable" : performanceTone(realized)}>
          {realized === null ? "—" : signedMoney(realized)}
        </strong>
      </div>
      <div>
        <small>Dividends &amp; interest</small>
        <strong>{eur.format(income)}</strong>
      </div>
      <div>
        <small>Fees</small>
        <strong>{fees ? `−${eur.format(fees)}` : eur.format(0)}</strong>
      </div>
      <div>
        <small>Total result</small>
        <strong className={totalReturn === null ? "unavailable" : performanceTone(totalReturn)}>
          {totalReturn === null ? "—" : signedMoney(totalReturn)}
        </strong>
      </div>
    </section>
  );
}

export function HoldingDetails({
  holding,
  onEditManual,
  onDeleteManual,
}: {
  holding: ScopedHolding;
  onEditManual: (source: HoldingSource, assetType: AssetType) => void;
  onDeleteManual: (source: HoldingSource) => void;
}) {
  const [activity, setActivity] = useState<ActivityResponse | null>(null);
  const costBasis = holding.performance.cost_basis_eur === null
    ? null
    : Number(holding.performance.cost_basis_eur);

  useEffect(() => {
    const params = new URLSearchParams({
      holding_key: holding.key, limit: "5", display_only: "true",
    });
    api<ActivityResponse>(`/activity?${params.toString()}`).then(setActivity).catch(() => null);
  }, [holding.key]);
  const income = Number(holding.performance.income_eur);
  const manualSources = holding.sources.filter((source) => source.broker === "manual");
  return (
    <div className="holding-details">
      <dl className="holding-summary-grid">
        <div className="cost-basis-inline">
          <dt>What you paid</dt>
          <dd>{costBasis !== null && costBasis >= 0 ? eur.format(costBasis) : "Unknown"}</dd>
        </div>
        <div>
          <dt>Worth now</dt>
          <dd>{eur.format(holding.totalValue)}</dd>
        </div>
        <div>
          <dt>Gain/loss</dt>
          <dd><PnlLine summary={holding.pnl} unavailable label="" /></dd>
        </div>
        <div>
          <dt>Dividends &amp; interest</dt>
          <dd>{eur.format(income)}</dd>
        </div>
      </dl>
      {manualSources.length > 0 && (
        <div className="manual-source-actions holding-manual-actions">
          {manualSources.map((source) => (
            <span key={source.provider_instrument_id}>
              <button type="button" className="secondary" onClick={() => onEditManual(source, holding.asset_type)}>
                Edit holding
              </button>
              <button type="button" className="text-button danger" onClick={() => void onDeleteManual(source)}>
                Delete
              </button>
            </span>
          ))}
        </div>
      )}
      <details className="holding-more">
        <summary>More details{holding.sources.length > 1 ? ` · ${holding.sources.length} brokers` : ""}</summary>
      <div className="canonical-strip">
        <span className="canonical-check">✓</span>
        <div>
          <strong>
            {holding.grouping === "company" ? "Several listings of one company" : "How this investment is matched"}
          </strong>
          {holding.grouping === "company" ? (
            <p>
              {holding.instrument_count} listed securities shown together · quantities remain
              separate below
            </p>
          ) : (
            <p>
              {holding.isin
                ? `Matched by ISIN ${holding.isin}`
                : `Matched as ${holding.symbol}`}
              {holding.sources.length > 1
                ? ` · combined from ${holding.sources.length} brokers`
                : ""}
            </p>
          )}
        </div>
      </div>
      <div className="source-detail-grid">
        {holding.sources.map((source) => (
          <article
            className="source-detail"
            key={`${source.connection_id}:${source.provider_instrument_id}`}
          >
            <header>
              <span className={`source-dot ${source.broker}`} />
              <div>
                <strong>{brokerName(source.broker)}</strong>
                <small>{source.provider_symbol}</small>
              </div>
              <strong>{eur.format(sourceValue(source))}</strong>
            </header>
            <dl>
              <div>
                <dt>Quantity</dt>
                <dd>{quantity.format(sourceQuantity(source))}</dd>
              </div>
              <div>
                <dt>Average price paid</dt>
                <dd>
                  {source.average_price
                    ? originalMoney(source.average_price, source.currency)
                    : "Not supplied"}
                </dd>
              </div>
              <div>
                <dt>Value in {source.currency}</dt>
                <dd>{originalMoney(source.current_value, source.currency)}</dd>
              </div>
              <SourcePnlMetric source={source} />
              {source.performance.realized_pnl_eur !== null && (
                <div>
                  <dt>Profit from sales</dt>
                  <dd className={performanceTone(Number(source.performance.realized_pnl_eur))}>
                    {signedMoney(Number(source.performance.realized_pnl_eur))}
                  </dd>
                </div>
              )}
              {Number(source.performance.income_eur) !== 0 && (
                <div>
                  <dt>Dividends &amp; interest</dt>
                  <dd>{eur.format(Number(source.performance.income_eur))}</dd>
                </div>
              )}
              <div>
                <dt>Security</dt>
                <dd title={source.canonical_name}>
                  {source.canonical_symbol}
                  {source.canonical_isin ? ` · ${source.canonical_isin}` : ""}
                </dd>
              </div>
              <div>
                <dt>Broker reference</dt>
                <dd title={source.provider_instrument_id}>{source.provider_instrument_id}</dd>
              </div>
            </dl>
            {source.note && <p className="manual-holding-note">{source.note}</p>}
            <footer>
              <span>
                {source.valued_at ? `Valued ${timestamp(source.valued_at)}` : "No valuation date"}
                {` · ${valuationLabel(source)}`}
                {source.is_stale ? " · Not up to date" : ""}
              </span>
            </footer>
          </article>
        ))}
      </div>
      <HoldingPerformanceSummary holding={holding} />
      </details>
      <div className="holding-activity-preview">
        <div className="panel-heading">
          <div><p className="eyebrow">Recent activity</p></div>
          <Link to="/activity">View all activity</Link>
        </div>
        {activity?.items.length ? activity.items.map((item) => (
          <div className="holding-activity-row" key={item.id}>
            <span className={`activity-kind ${item.transaction_type}`}>{activityLabels[item.transaction_type]}</span>
            <strong>{item.symbol}</strong>
            <span>{new Date(item.executed_at).toLocaleDateString()}</span>
            <span>{item.value_eur === null ? `${originalMoney(item.value, item.currency)}` : eur.format(Number(item.value_eur))}</span>
          </div>
        )) : <p className="muted">No buys, sells or dividends recorded for this holding yet.</p>}
      </div>
    </div>
  );
}
