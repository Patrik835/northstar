import { useEffect, useMemo, useState } from "react";
import { api } from "../../api/client";
import type {
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
};
const assetLabels: Record<AssetType, string> = {
  stock: "Stock",
  etf: "ETF",
  crypto: "Crypto",
  cash: "Cash",
  other: "Other",
};

type AssetGroup = "all" | "equities" | "crypto" | "other";

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

export function HoldingsPage() {
  const [portfolio, setPortfolio] = useState<HoldingsResponse | null>(null);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [assetGroup, setAssetGroup] = useState<AssetGroup>("all");
  const [platform, setPlatform] = useState<Broker | "all">("all");
  const [expanded, setExpanded] = useState<string | null>(null);

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
      const totalQuantity = sources.reduce(
        (total, source) => total + sourceQuantity(source),
        0,
      );
      return [{ ...holding, sources, totalValue, totalQuantity }];
    });
  }, [platform, portfolio]);

  const visibleHoldings = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return scopedHoldings.filter((holding) => {
      if (!inGroup(holding.asset_type, assetGroup)) return false;
      if (!needle) return true;
      return [
        holding.symbol,
        holding.name,
        holding.isin,
        ...holding.sources.flatMap((source) => [
          source.provider_symbol,
          source.provider_name,
        ]),
      ].some((value) => value?.toLowerCase().includes(needle));
    });
  }, [assetGroup, scopedHoldings, search]);

  const equityValue = scopedHoldings
    .filter((holding) => inGroup(holding.asset_type, "equities"))
    .reduce((total, holding) => total + holding.totalValue, 0);
  const cryptoValue = scopedHoldings
    .filter((holding) => holding.asset_type === "crypto")
    .reduce((total, holding) => total + holding.totalValue, 0);

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
        <span className="as-of">Current values in EUR</span>
      </header>

      {error && <p className="error">{error}</p>}
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
          <small>{platform === "all" ? "Across every connected platform" : "Platform value"}</small>
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
            <div className="holding-table-head" aria-hidden="true">
              <span>Instrument</span>
              <span>Type</span>
              <span>Quantity</span>
              <span>Platforms</span>
              <span>Current value</span>
              <span />
            </div>
            {visibleHoldings.map((holding) => {
              const isOpen = expanded === holding.key;
              return (
                <article className={`holding-entry${isOpen ? " open" : ""}`} key={holding.key}>
                  <button
                    className="holding-row"
                    aria-expanded={isOpen}
                    onClick={() => setExpanded(isOpen ? null : holding.key)}
                  >
                    <span className="holding-identity">
                      <span className={`asset-mark ${holding.asset_type}`}>
                        {holding.symbol.slice(0, 2)}
                      </span>
                      <span>
                        <strong>{holding.symbol}</strong>
                        <small>{holding.name}</small>
                      </span>
                    </span>
                    <span>
                      <span className={`asset-pill ${holding.asset_type}`}>
                        {assetLabels[holding.asset_type]}
                      </span>
                    </span>
                    <span className="quantity-cell">
                      {quantity.format(holding.totalQuantity)}
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
  totalQuantity: number;
};

function HoldingDetails({ holding }: { holding: ScopedHolding }) {
  return (
    <div className="holding-details">
      <div className="canonical-strip">
        <span className="canonical-check">✓</span>
        <div>
          <strong>Canonical instrument</strong>
          <p>
            {holding.isin ? `Matched by ISIN ${holding.isin}` : `Matched as ${holding.symbol}`}
            {holding.sources.length > 1
              ? ` · ${holding.sources.length} broker aliases combined`
              : " · 1 broker alias"}
          </p>
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
              <div>
                <dt>Provider ID</dt>
                <dd title={source.provider_instrument_id}>{source.provider_instrument_id}</dd>
              </div>
            </dl>
            <footer>
              {source.last_synced_at
                ? `Synced ${new Date(source.last_synced_at).toLocaleString()}`
                : "Awaiting first successful sync"}
            </footer>
          </article>
        ))}
      </div>
    </div>
  );
}
