import { useEffect, useMemo, useState } from "react";
import { api } from "../../api/client";
import type {
  ActivityResponse,
  AssetType,
  Broker,
  Holding,
  HoldingSource,
  HoldingsResponse,
} from "../../api/types";
import { EmptyState } from "../../components/EmptyState";
import { Link } from "../../routing/Router";

const eur = new Intl.NumberFormat("en-IE", {
  style: "currency",
  currency: "EUR",
  maximumFractionDigits: 2,
});
const quantity = new Intl.NumberFormat("en-IE", { maximumFractionDigits: 8 });
const brokerLabels: Record<Broker, string> = {
  trading212: "Trading 212",
  trading212_crypto: "Trading 212 Crypto",
  etoro: "eToro",
  binance: "Binance",
  xtb: "XTB",
};
const assetLabels: Record<AssetType, string> = {
  stock: "Stock",
  etf: "ETF",
  crypto: "Crypto",
  cash: "Cash",
  other: "Other",
};

type AssetGroup = "all" | "equities" | "crypto" | "other";
type SortKey = "value" | "pnl";
type SortDirection = "asc" | "desc";

function inGroup(type: AssetType, group: AssetGroup) {
  if (group === "all") return true;
  if (group === "equities") return type === "stock" || type === "etf";
  if (group === "crypto") return type === "crypto";
  return type === "cash" || type === "other";
}

function sourceValue(source: HoldingSource) {
  return Number(source.current_value_eur);
}

function sourceQuantity(source: HoldingSource) {
  return Number(source.quantity);
}

function originalMoney(value: string, currency: string) {
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

function brokerLabel(broker: Broker) {
  return brokerLabels[broker] ?? broker;
}

function timestamp(value: string | null) {
  if (!value) return "Awaiting first valuation";
  return new Date(value).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

function valuationLabel(source: HoldingSource) {
  if (source.valuation_source === "last_trade") return "Estimated from last trade";
  if (source.valuation_source === "market") return "Market price";
  if (source.valuation_source === "statement") return "Imported statement";
  return "Provider value";
}

type PnlSummary = {
  value: number;
  percentage: number | null;
  sourceCount: number;
  totalSources: number;
  calculatedCount: number;
  hasPartialCoverage: boolean;
};

type SourcePnl = {
  valueEur: number;
  kind: "calculated" | "reported";
};

function preferredSourcePnl(source: HoldingSource): SourcePnl | null {
  if (source.performance.open_pnl_eur === null) return null;
  return {
    valueEur: Number(source.performance.open_pnl_eur),
    kind: source.performance.open_pnl_source === "calculated" ? "calculated" : "reported",
  };
}

function summarizePnl(sources: HoldingSource[]): PnlSummary | null {
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
    percentage: costBasis > 0 ? (value * 100) / costBasis : null,
    sourceCount: available.length,
    totalSources: sources.length,
    calculatedCount: available.filter((item) => item.pnl.kind === "calculated").length,
    hasPartialCoverage: false,
  };
}

function signedMoney(value: number) {
  return `${value > 0 ? "+" : ""}${eur.format(value)}`;
}

function signedPercentage(value: number) {
  return `${value > 0 ? "+" : ""}${value.toFixed(2)}%`;
}

function PnlLine({
  summary,
  unavailable = false,
}: {
  summary: PnlSummary | null;
  unavailable?: boolean;
}) {
  if (!summary) {
    return unavailable ? <span className="pnl-summary unavailable">P/L unavailable</span> : null;
  }
  const tone =
    summary.value > 0 ? "positive" : summary.value < 0 ? "negative" : "neutral";
  const partial = summary.sourceCount < summary.totalSources || summary.hasPartialCoverage;
  return (
    <span
      className={`pnl-summary ${tone}`}
      title={summary.calculatedCount
        ? "Calculated from imported trades; broker-reported P/L is used where trade history is incomplete"
        : "Broker-reported P/L"}
    >
      <span>Open P/L {signedMoney(summary.value)}</span>
      {summary.percentage !== null && <span>{signedPercentage(summary.percentage)}</span>}
      {partial && (
        <em title={`Reported by ${summary.sourceCount} of ${summary.totalSources} sources`}>
          partial
        </em>
      )}
    </span>
  );
}

function SourcePnlMetric({ source }: { source: HoldingSource }) {
  const pnl = preferredSourcePnl(source);
  if (!pnl) {
    return (
      <div>
        <dt>P/L</dt>
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
      <dt>Open P/L</dt>
      <dd className={`pnl-source-value ${pnl.valueEur >= 0 ? "positive" : "negative"}`}>
        <span>
          {pnl.kind === "reported" && source.reported_pnl !== null
            ? originalMoney(source.reported_pnl, source.currency)
            : signedMoney(pnl.valueEur)}
        </span>
        {secondary && <small>{secondary}</small>}
        <small>{pnl.kind === "calculated" ? "Calculated from trades" : "Reported by broker"}</small>
      </dd>
    </div>
  );
}

export function HoldingsPage() {
  const [portfolio, setPortfolio] = useState<HoldingsResponse | null>(null);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [assetGroup, setAssetGroup] = useState<AssetGroup>("all");
  const [platform, setPlatform] = useState<Broker | "all">("all");
  const [expanded, setExpanded] = useState<string | null>(null);
  const [sortKey, setSortKey] = useState<SortKey>("value");
  const [sortDirection, setSortDirection] = useState<SortDirection>("desc");

  useEffect(() => {
    api<HoldingsResponse>("/holdings")
      .then(setPortfolio)
      .catch((reason: Error) => setError(reason.message));
  }, []);

  const selectedTotal = useMemo(() => {
    if (!portfolio) return 0;
    if (platform === "all") return Number(portfolio.total_value_eur);
    return Number(
      portfolio.sources.find((source) => source.label === platform)?.value_eur ?? 0,
    );
  }, [platform, portfolio]);

  const scopedHoldings = useMemo(() => {
    if (!portfolio) return [];
    return portfolio.holdings.flatMap((holding) => {
      const sources =
        platform === "all"
          ? holding.sources
          : holding.sources.filter((source) => source.broker === platform);
      if (!sources.length) return [];
      const totalValue = sources.reduce((total, source) => total + sourceValue(source), 0);
      const instrumentIds = new Set(
        sources.map(
          (source) =>
            source.canonical_instrument_id ??
            `${source.broker}:${source.provider_instrument_id}`,
        ),
      );
      const symbols = Array.from(
        new Set(sources.map((source) => source.canonical_symbol)),
      ).sort();
      const isCompanyGroup = instrumentIds.size > 1;
      const staleConnectionIds = new Set(
        sources.filter((source) => source.is_stale).map((source) => source.connection_id),
      );
      const asOf = sources.reduce<string | null>((latest, source) => {
        if (!source.valued_at) return latest;
        if (!latest || new Date(source.valued_at) > new Date(latest)) return source.valued_at;
        return latest;
      }, null);
      const totalQuantity = isCompanyGroup
        ? null
        : sources.reduce((total, source) => total + sourceQuantity(source), 0);
      const calculatedSources = sources.filter(
        (source) => source.gain_coverage === "complete" && source.calculated_cost_eur !== null,
      );
      const calculatedCost = calculatedSources.length
        ? calculatedSources.reduce(
          (total, source) => total + Number(source.calculated_cost_eur), 0,
        ) : null;
      return [
        {
          ...holding,
          grouping: isCompanyGroup ? ("company" as const) : ("instrument" as const),
          instrument_count: instrumentIds.size,
          symbol: isCompanyGroup ? symbols.join(" / ") : symbols[0],
          symbols,
          name: isCompanyGroup ? holding.name : sources[0].canonical_name,
          isin: isCompanyGroup ? null : sources[0].canonical_isin,
          sources,
          totalValue,
          totalQuantity,
          pnl: summarizePnl(sources),
          as_of: asOf,
          is_stale: staleConnectionIds.size > 0,
          stale_source_count: staleConnectionIds.size,
          has_estimated_value: sources.some((source) => source.is_estimated),
          calculated_cost_eur: calculatedCost === null ? null : String(calculatedCost),
          calculated_gain_eur: calculatedCost === null ? null : String(totalValue - calculatedCost),
          calculated_gain_percentage: calculatedCost
            ? String(((totalValue - calculatedCost) * 100) / calculatedCost) : null,
          gain_coverage: calculatedSources.length === sources.length &&
            sources.every((source) => source.gain_coverage === "complete")
            ? "complete" as const
            : calculatedSources.length ? "partial" as const : "unavailable" as const,
        },
      ];
    });
  }, [platform, portfolio]);

  const visibleHoldings = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return scopedHoldings
      .filter((holding) => {
        if (!inGroup(holding.asset_type, assetGroup)) return false;
        if (!needle) return true;
        return [
          holding.symbol,
          holding.name,
          holding.isin,
          ...holding.symbols,
          ...holding.sources.flatMap((source) => [
            source.provider_symbol,
            source.provider_name,
            source.canonical_symbol,
            source.canonical_name,
            source.canonical_isin,
          ]),
        ].some((value) => value?.toLowerCase().includes(needle));
      })
      .sort((left, right) => {
        if (sortKey === "pnl") {
          if (left.pnl === null && right.pnl === null) {
            return left.symbol.localeCompare(right.symbol);
          }
          if (left.pnl === null) return 1;
          if (right.pnl === null) return -1;
        }
        const leftValue = sortKey === "value" ? left.totalValue : left.pnl!.value;
        const rightValue = sortKey === "value" ? right.totalValue : right.pnl!.value;
        const difference = leftValue - rightValue;
        if (difference === 0) return left.symbol.localeCompare(right.symbol);
        return sortDirection === "asc" ? difference : -difference;
      });
  }, [assetGroup, scopedHoldings, search, sortDirection, sortKey]);

  function changeSort(nextKey: SortKey) {
    if (sortKey === nextKey) {
      setSortDirection((current) => (current === "desc" ? "asc" : "desc"));
      return;
    }
    setSortKey(nextKey);
    setSortDirection("desc");
  }

  const equityValue = scopedHoldings
    .filter((holding) => inGroup(holding.asset_type, "equities"))
    .reduce((total, holding) => total + holding.totalValue, 0);
  const cryptoValue = scopedHoldings
    .filter((holding) => holding.asset_type === "crypto")
    .reduce((total, holding) => total + holding.totalValue, 0);
  const portfolioPnl = summarizePnl(scopedHoldings.flatMap((holding) => holding.sources));
  const equityPnl = summarizePnl(
    scopedHoldings
      .filter((holding) => inGroup(holding.asset_type, "equities"))
      .flatMap((holding) => holding.sources),
  );
  const cryptoPnl = summarizePnl(
    scopedHoldings
      .filter((holding) => holding.asset_type === "crypto")
      .flatMap((holding) => holding.sources),
  );
  const scopedSources = scopedHoldings.flatMap((holding) => holding.sources);
  const scopedAsOf = scopedSources.reduce<string | null>((latest, source) => {
    if (!source.valued_at) return latest;
    if (!latest || new Date(source.valued_at) > new Date(latest)) return source.valued_at;
    return latest;
  }, null);
  const staleConnectionCount = new Set(
    scopedSources.filter((source) => source.is_stale).map((source) => source.connection_id),
  ).size;
  const reconciliationWarnings =
    platform === "all"
      ? (portfolio?.reconciliation_warnings ?? [])
      : (portfolio?.reconciliation_warnings.filter((warning) => warning.broker === platform) ?? []);

  return (
    <>
      <header className="page-header holdings-header">
        <div>
          <p className="eyebrow">Canonical portfolio</p>
          <h1>Holdings</h1>
          <p className="page-intro">
            One clean view of every asset, with each broker position preserved underneath.
          </p>
        </div>
        <span className={`as-of holdings-as-of${staleConnectionCount ? " stale" : ""}`}>
          <span className="freshness-dot" />
          <span>
            {scopedAsOf ? `Updated ${timestamp(scopedAsOf)}` : "Awaiting first valuation"}
            <small>Values in EUR</small>
          </span>
          {staleConnectionCount > 0 && (
            <em>
              {staleConnectionCount} stale source{staleConnectionCount === 1 ? "" : "s"}
            </em>
          )}
        </span>
      </header>

      {error && <p className="error">{error}</p>}
      {reconciliationWarnings.map((warning) => (
        <p className="holdings-warning reconciliation-warning" key={warning.connection_id}>
          <strong>Source total needs attention.</strong> {warning.message}
        </p>
      ))}
      {portfolio?.unmatched_positions ? (
        <p className="holdings-warning">
          {portfolio.unmatched_positions} existing position
          {portfolio.unmatched_positions === 1 ? " is" : "s are"} waiting for the next
          broker sync to receive a canonical match.
        </p>
      ) : null}

      <section className="holdings-metrics">
        <button
          type="button"
          className={`holding-metric filter-card total${assetGroup === "all" ? " active" : ""}`}
          aria-pressed={assetGroup === "all"}
          aria-controls="holdings-instruments"
          onClick={() => setAssetGroup("all")}
        >
          <span>{platform === "all" ? "Combined portfolio" : brokerLabel(platform)}</span>
          <strong>{portfolio ? eur.format(selectedTotal) : "—"}</strong>
          <small>
            {platform === "all" ? "Across every connected platform" : "Platform value"}
          </small>
          {portfolio && <PnlLine summary={portfolioPnl} unavailable />}
        </button>
        <button
          type="button"
          className={`holding-metric filter-card equities${assetGroup === "equities" ? " active" : ""}`}
          aria-pressed={assetGroup === "equities"}
          aria-controls="holdings-instruments"
          onClick={() => setAssetGroup("equities")}
        >
          <span>Stocks & ETFs</span>
          <strong>{portfolio ? eur.format(equityValue) : "—"}</strong>
          <small>Combined securities</small>
          {portfolio && <PnlLine summary={equityPnl} unavailable />}
        </button>
        <button
          type="button"
          className={`holding-metric filter-card crypto${assetGroup === "crypto" ? " active" : ""}`}
          aria-pressed={assetGroup === "crypto"}
          aria-controls="holdings-instruments"
          onClick={() => setAssetGroup("crypto")}
        >
          <span>Crypto</span>
          <strong>{portfolio ? eur.format(cryptoValue) : "—"}</strong>
          <small>Across crypto platforms</small>
          {portfolio && <PnlLine summary={cryptoPnl} unavailable />}
        </button>
        <article className="holding-metric count">
          <span>Instruments</span>
          <strong>{portfolio ? scopedHoldings.length : "—"}</strong>
          <small>{portfolio?.position_count ?? "—"} source positions</small>
        </article>
      </section>

      <section className="panel holdings-panel" id="holdings-instruments">
        <div className="holdings-toolbar">
          <div>
            <p className="toolbar-label">Platform</p>
            <div className="platform-switch" aria-label="Filter by investment platform">
              <button
                className={platform === "all" ? "active" : ""}
                onClick={() => setPlatform("all")}
              >
                All platforms
              </button>
              {portfolio?.sources.map((source) => (
                <button
                  key={source.label}
                  className={platform === source.label ? "active" : ""}
                  onClick={() => setPlatform(source.label as Broker)}
                >
                  {brokerLabel(source.label as Broker)}
                  <small>{source.percentage}%</small>
                </button>
              ))}
            </div>
          </div>

          <div className="holding-filter-row">
            <div className="asset-tabs" aria-label="Filter by asset class">
              {(
                [
                  ["all", "All assets"],
                  ["equities", "Stocks & ETFs"],
                  ["crypto", "Crypto"],
                  ["other", "Cash & other"],
                ] as Array<[AssetGroup, string]>
              ).map(([value, label]) => (
                <button
                  key={value}
                  className={assetGroup === value ? "active" : ""}
                  onClick={() => setAssetGroup(value)}
                >
                  {label}
                </button>
              ))}
            </div>
            <label className="holding-search">
              <span>Search holdings</span>
              <input
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Name, ticker, ISIN…"
              />
            </label>
          </div>
        </div>

        {visibleHoldings.length ? (
          <div className="holdings-table">
            <div className="holding-table-head">
              <span>Instrument</span>
              <span>Type</span>
              <span>Quantity</span>
              <span>Platforms</span>
              <span className="holding-sort-column">
                <button
                  type="button"
                  className={sortKey === "value" ? "active" : ""}
                  aria-pressed={sortKey === "value"}
                  onClick={() => changeSort("value")}
                >
                  Value {sortKey === "value" && (sortDirection === "desc" ? "↓" : "↑")}
                </button>
                <span>/</span>
                <button
                  type="button"
                  className={sortKey === "pnl" ? "active" : ""}
                  aria-pressed={sortKey === "pnl"}
                  onClick={() => changeSort("pnl")}
                >
                  Open P/L {sortKey === "pnl" && (sortDirection === "desc" ? "↓" : "↑")}
                </button>
              </span>
              <span />
            </div>
            {visibleHoldings.map((holding) => {
              const isOpen = expanded === holding.key;
              const isCompanyGroup = holding.grouping === "company";
              return (
                <article className={`holding-entry${isOpen ? " open" : ""}`} key={holding.key}>
                  <button
                    className="holding-row"
                    aria-expanded={isOpen}
                    onClick={() => setExpanded(isOpen ? null : holding.key)}
                  >
                    <span className="holding-identity">
                      <span className={`asset-mark ${holding.asset_type}`}>
                        {(isCompanyGroup ? holding.name : holding.symbol).slice(0, 2)}
                      </span>
                      <span>
                        <strong>{isCompanyGroup ? holding.name : holding.symbol}</strong>
                        <small>
                          {isCompanyGroup
                            ? `${holding.symbols.join(" · ")} · combined company exposure`
                            : holding.name}
                        </small>
                        {(holding.is_stale || holding.has_estimated_value) && (
                          <span className="holding-statuses">
                            {holding.is_stale && <em className="stale">Stale</em>}
                            {holding.has_estimated_value && <em>Estimated</em>}
                          </span>
                        )}
                      </span>
                    </span>
                    <span>
                      <span className={`asset-pill ${holding.asset_type}`}>
                        {assetLabels[holding.asset_type]}
                      </span>
                    </span>
                    <span className="quantity-cell">
                      {holding.totalQuantity === null
                        ? `${holding.instrument_count} securities`
                        : quantity.format(holding.totalQuantity)}
                    </span>
                    <span className="source-badges">
                      {holding.sources.map((source) => (
                        <span
                          className={`source-badge ${source.broker}`}
                          key={`${source.connection_id}:${source.provider_instrument_id}`}
                        >
                          {brokerLabel(source.broker)}
                        </span>
                      ))}
                    </span>
                    <span className="value-cell">
                      <strong>{eur.format(holding.totalValue)}</strong>
                      <small>
                        {selectedTotal
                          ? `${((holding.totalValue * 100) / selectedTotal).toFixed(2)}%`
                          : "0.00%"}
                      </small>
                      <PnlLine summary={holding.pnl} />
                    </span>
                    <span className="expand-mark">{isOpen ? "−" : "+"}</span>
                  </button>
                  {isOpen && <HoldingDetails holding={holding} />}
                </article>
              );
            })}
          </div>
        ) : portfolio ? (
          <EmptyState title="No matching holdings">
            {portfolio.position_count
              ? "Try another platform, asset class, or search term."
              : "Connect and synchronize a broker to see every holding here. "}
            {!portfolio.position_count && <Link to="/connections">Add a connection</Link>}
          </EmptyState>
        ) : (
          <div className="holdings-loading">Loading your consolidated portfolio…</div>
        )}
      </section>
    </>
  );
}

type ScopedHolding = Holding & {
  totalValue: number;
  totalQuantity: number | null;
  pnl: PnlSummary | null;
};

function performanceTone(value: number) {
  return value > 0 ? "positive" : value < 0 ? "negative" : "neutral";
}

function HoldingPerformanceSummary({ holding }: { holding: ScopedHolding }) {
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
    <section className="holding-performance-strip" aria-label="Imported performance history">
      <div className="performance-strip-heading">
        <span>Performance history</span>
        <small>
          {performance.coverage === "complete"
            ? "Complete trade coverage"
            : "Partial history · incomplete totals are hidden"}
        </small>
      </div>
      <div>
        <small>{performance.coverage === "complete" ? "Realized" : "Known realized"}</small>
        <strong className={realized === null ? "unavailable" : performanceTone(realized)}>
          {realized === null ? "—" : signedMoney(realized)}
        </strong>
      </div>
      <div>
        <small>Income</small>
        <strong>{eur.format(income)}</strong>
      </div>
      <div>
        <small>Fees</small>
        <strong>{fees ? `−${eur.format(fees)}` : eur.format(0)}</strong>
      </div>
      <div>
        <small>Total return</small>
        <strong className={totalReturn === null ? "unavailable" : performanceTone(totalReturn)}>
          {totalReturn === null ? "—" : signedMoney(totalReturn)}
        </strong>
      </div>
    </section>
  );
}

function HoldingDetails({ holding }: { holding: ScopedHolding }) {
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
  return (
    <div className="holding-details">
      <div className="canonical-strip">
        <span className="canonical-check">✓</span>
        <div>
          <strong>
            {holding.grouping === "company" ? "Company exposure" : "Canonical instrument"}
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
                ? ` · ${holding.sources.length} broker aliases combined`
                : " · 1 broker alias"}
            </p>
          )}
        </div>
        <span className="canonical-metrics">
          {costBasis !== null && costBasis >= 0 && (
            <span className="cost-basis-inline">
              <small>Cost basis</small>
              <strong>{eur.format(costBasis)}</strong>
            </span>
          )}
          <PnlLine summary={holding.pnl} />
        </span>
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
                <strong>{brokerLabel(source.broker)}</strong>
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
                <dt>Average price</dt>
                <dd>
                  {source.average_price
                    ? originalMoney(source.average_price, source.currency)
                    : "Not supplied"}
                </dd>
              </div>
              <div>
                <dt>Original value</dt>
                <dd>{originalMoney(source.current_value, source.currency)}</dd>
              </div>
              <SourcePnlMetric source={source} />
              {source.performance.realized_pnl_eur !== null && (
                <div>
                  <dt>Realized P/L</dt>
                  <dd className={performanceTone(Number(source.performance.realized_pnl_eur))}>
                    {signedMoney(Number(source.performance.realized_pnl_eur))}
                  </dd>
                </div>
              )}
              {Number(source.performance.income_eur) !== 0 && (
                <div>
                  <dt>Imported income</dt>
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
                <dt>Provider ID</dt>
                <dd title={source.provider_instrument_id}>{source.provider_instrument_id}</dd>
              </div>
            </dl>
            <footer>
              {source.valued_at ? `Valued ${timestamp(source.valued_at)}` : "No valuation date"}
              {` · ${valuationLabel(source)}`}
              {source.is_stale ? " · Stale" : ""}
            </footer>
          </article>
        ))}
      </div>
      <HoldingPerformanceSummary holding={holding} />
      <div className="holding-activity-preview">
        <div className="panel-heading">
          <div><p className="eyebrow">Recent activity</p><h3>{holding.name}</h3></div>
          <Link to="/activity">View all activity</Link>
        </div>
        {activity?.items.length ? activity.items.map((item) => (
          <div className="holding-activity-row" key={item.id}>
            <span className={`activity-kind ${item.transaction_type}`}>{item.transaction_type}</span>
            <strong>{item.symbol}</strong>
            <span>{new Date(item.executed_at).toLocaleDateString()}</span>
            <span>{item.value_eur === null ? `${originalMoney(item.value, item.currency)}` : eur.format(Number(item.value_eur))}</span>
          </div>
        )) : <p className="muted">No imported activity for this holding yet.</p>}
      </div>
    </div>
  );
}
