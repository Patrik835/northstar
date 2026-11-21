import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { FormEvent } from "react";
import { api } from "../../api/client";
import type {
  AssetType,
  Broker,
  HoldingSource,
  HoldingsResponse,
  ManualPosition,
} from "../../api/types";
import { EmptyState } from "../../components/EmptyState";
import { CsvDownloadButton } from "../../components/CsvDownloadButton";
import { brokerName } from "../../domain/brokers";
import { Link } from "../../routing/Router";
import { AssetPicker } from "./AssetPicker";
import type { AssetOption } from "./AssetPicker";
import { eur, assetLabels, inGroup, sourceValue, sourceQuantity, timestamp, summarizePnl, combinePerformance, type AssetGroup, type SortKey, type SortDirection } from "./holdingMath";
import { PnlLine, HoldingDetails } from "./HoldingDetails";

export function HoldingsPage() {
  const [portfolio, setPortfolio] = useState<HoldingsResponse | null>(null);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [assetGroup, setAssetGroup] = useState<AssetGroup>("all");
  const [platform, setPlatform] = useState<Broker | "all">("all");
  const [expanded, setExpanded] = useState<string | null>(null);
  const [sortKey, setSortKey] = useState<SortKey>("value");
  const [sortDirection, setSortDirection] = useState<SortDirection>("desc");
  const [manualEditor, setManualEditor] = useState<{
    id: string | null;
    source: HoldingSource | null;
    assetType: "stock" | "etf" | "crypto";
  } | null>(null);
  const [manualError, setManualError] = useState("");
  const [manualNotice, setManualNotice] = useState("");
  const [savingManual, setSavingManual] = useState(false);
  const [selectedAsset, setSelectedAsset] = useState<AssetOption | null>(null);
  const purchasePriceInput = useRef<HTMLInputElement>(null);
  const manualAssets = useMemo<AssetOption[]>(() => (portfolio?.holdings ?? [])
    .filter((holding) => ["stock", "etf", "crypto"].includes(holding.asset_type))
    .flatMap((holding) => holding.sources.map((source) => ({
      ticker: source.canonical_symbol,
      name: source.canonical_name === source.canonical_symbol
        ? source.provider_name ?? source.canonical_name : source.canonical_name,
      asset_type: holding.asset_type as AssetOption["asset_type"],
      isin: source.canonical_isin,
    }))), [portfolio]);

  const loadPortfolio = useCallback(() => {
    return api<HoldingsResponse>("/holdings")
      .then(setPortfolio)
      .catch((reason: Error) => setError(reason.message));
  }, []);

  useEffect(() => {
    void loadPortfolio();
  }, [loadPortfolio]);

  function openManualCreate() {
    setManualError("");
    setSelectedAsset(null);
    setManualEditor({ id: null, source: null, assetType: "stock" });
  }

  // Deep link from onboarding: /holdings?add=1 opens the "Add a position" form directly.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get("add") !== "1") return;
    params.delete("add");
    const query = params.toString();
    window.history.replaceState({}, "", `${window.location.pathname}${query ? `?${query}` : ""}`);
    openManualCreate();
  }, []);

  function openManualEdit(source: HoldingSource, assetType: AssetType) {
    if (source.broker !== "manual") return;
    setManualError("");
    setSelectedAsset({
      ticker: source.provider_symbol,
      name: source.provider_name ?? source.canonical_name,
      asset_type: assetType === "etf" || assetType === "crypto" ? assetType : "stock",
      isin: source.canonical_isin,
    });
    setManualEditor({
      id: source.provider_instrument_id.replace(/^MANUAL:/, ""),
      source,
      assetType: assetType === "etf" || assetType === "crypto" ? assetType : "stock",
    });
  }

  async function submitManual(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!manualEditor) return;
    if (!selectedAsset) {
      setManualError("Choose an asset from the suggestions first.");
      return;
    }
    setSavingManual(true);
    setManualError("");
    const form = new FormData(event.currentTarget);
    const averagePrice = String(form.get("average_price") ?? "").trim();
    const currency = String(form.get("currency") ?? "EUR");
    const payload = {
      ticker: selectedAsset.ticker,
      name: selectedAsset.name,
      asset_type: selectedAsset.asset_type,
      quantity: String(form.get("quantity") ?? ""),
      average_price: averagePrice || null,
      current_price: null,
      currency,
      isin: selectedAsset.isin,
      note: String(form.get("note") ?? "").trim() || null,
    };
    try {
      await api<ManualPosition>(
        manualEditor.id ? `/holdings/manual/${manualEditor.id}` : "/holdings/manual",
        {
          method: manualEditor.id ? "PUT" : "POST",
          body: JSON.stringify(payload),
        },
      );
      setManualNotice(manualEditor.id ? "Holding updated." : "Holding added.");
      setManualEditor(null);
      await loadPortfolio();
    } catch (reason) {
      setManualError(reason instanceof Error ? reason.message : "Could not save position");
    } finally {
      setSavingManual(false);
    }
  }

  async function deleteManual(source: HoldingSource) {
    const id = source.provider_instrument_id.replace(/^MANUAL:/, "");
    if (!window.confirm(`Delete your ${source.provider_symbol} holding?`)) return;
    try {
      await api(`/holdings/manual/${id}`, { method: "DELETE" });
      setManualNotice("Holding deleted.");
      await loadPortfolio();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not delete position");
    }
  }

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
      return [
        {
          ...holding,
          performance: platform === "all" ? holding.performance : combinePerformance(sources),
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

  const exportPath = useMemo(() => {
    const params = new URLSearchParams({ asset_group: assetGroup });
    if (platform !== "all") params.set("broker", platform);
    if (search.trim()) params.set("search", search.trim());
    return `/exports/holdings.csv?${params.toString()}`;
  }, [assetGroup, platform, search]);

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
  const otherValue = scopedHoldings
    .filter((holding) => inGroup(holding.asset_type, "other"))
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
          <p className="eyebrow">All your investments</p>
          <h1>Holdings</h1>
        </div>
        <div className="page-header-actions">
          <div className="holdings-header-buttons">
            <button type="button" className="secondary" onClick={openManualCreate}>
              Add holding
            </button>
            <CsvDownloadButton path={exportPath} disabled={!portfolio} />
          </div>
          <span className={`as-of holdings-as-of${staleConnectionCount ? " stale" : ""}`}>
            <span className="freshness-dot" />
            <span>
              {scopedAsOf ? `Updated ${timestamp(scopedAsOf)}` : "Waiting for the first prices"}
              <small>Values in EUR</small>
            </span>
            {staleConnectionCount > 0 && (
              <em>
                {staleConnectionCount} source{staleConnectionCount === 1 ? " is" : "s are"} not up to date
              </em>
            )}
          </span>
        </div>
      </header>

      {error && <p className="error">{error}</p>}
      {manualNotice && <p className="notice">{manualNotice}</p>}
      {reconciliationWarnings.map((warning) => (
        <p className="holdings-warning reconciliation-warning" key={warning.connection_id}>
          <strong>Totals from this broker don't add up yet.</strong> {warning.message}
        </p>
      ))}
      {portfolio?.unmatched_positions ? (
        <p className="holdings-warning">
          {portfolio.unmatched_positions} existing position
          {portfolio.unmatched_positions === 1 ? " is" : "s are"} waiting for the next
          broker sync to be matched with your other holdings.
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
          <span>{platform === "all" ? "Everything" : brokerName(platform)}</span>
          <strong>{portfolio ? eur.format(selectedTotal) : "—"}</strong>
          <small>{portfolio ? `${scopedHoldings.length} investments` : "Loading…"}</small>
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
          {portfolio && <PnlLine summary={cryptoPnl} unavailable />}
        </button>
        {otherValue > 0 && (
          <button
            type="button"
            className={`holding-metric filter-card other${assetGroup === "other" ? " active" : ""}`}
            aria-pressed={assetGroup === "other"}
            aria-controls="holdings-instruments"
            onClick={() => setAssetGroup("other")}
          >
            <span>Cash &amp; other</span>
            <strong>{eur.format(otherValue)}</strong>
          </button>
        )}
      </section>

      <section className="panel holdings-panel" id="holdings-instruments">
        <div className="holdings-toolbar simple">
          <label className="holding-search">
            <span>Search</span>
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Name or ticker…"
            />
          </label>
          {(portfolio?.sources.length ?? 0) > 1 && (
            <label className="platform-select">
              <span>Broker</span>
              <select
                value={platform}
                onChange={(event) => setPlatform(event.target.value as Broker | "all")}
              >
                <option value="all">All brokers</option>
                {portfolio?.sources.map((source) => (
                  <option key={source.label} value={source.label}>
                    {brokerName(source.label as Broker)} ({source.percentage}%)
                  </option>
                ))}
              </select>
            </label>
          )}
        </div>

        {visibleHoldings.length ? (
          <div className="holdings-table">
            <div className="holding-table-head">
              <span>Investment</span>
              <span className="holding-sort-column">
                <button
                  type="button"
                  className={sortKey === "value" ? "active" : ""}
                  aria-pressed={sortKey === "value"}
                  onClick={() => changeSort("value")}
                >
                  Value {sortKey === "value" && (sortDirection === "desc" ? "↓" : "↑")}
                </button>
              </span>
              <span className="holding-sort-column">
                <button
                  type="button"
                  className={sortKey === "pnl" ? "active" : ""}
                  aria-pressed={sortKey === "pnl"}
                  onClick={() => changeSort("pnl")}
                >
                  Gain/loss {sortKey === "pnl" && (sortDirection === "desc" ? "↓" : "↑")}
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
                        {holding.symbol.slice(0, 2)}
                      </span>
                      <span>
                        <strong>{holding.name}</strong>
                        <small>
                          {isCompanyGroup
                            ? holding.symbols.join(" · ")
                            : `${holding.symbol} · ${assetLabels[holding.asset_type]}`}
                          {holding.sources.length > 1 ? ` · ${holding.sources.length} brokers` : ""}
                        </small>
                        {(holding.is_stale || holding.has_estimated_value) && (
                          <span className="holding-statuses">
                            {holding.is_stale && <em className="stale">Not up to date</em>}
                            {holding.has_estimated_value && <em>Estimated value</em>}
                          </span>
                        )}
                      </span>
                    </span>
                    <span className="value-cell">
                      <strong>{eur.format(holding.totalValue)}</strong>
                      <small>
                        {selectedTotal
                          ? `${((holding.totalValue * 100) / selectedTotal).toFixed(1)}% of portfolio`
                          : ""}
                      </small>
                    </span>
                    <span className="gain-cell">
                      {holding.pnl ? <PnlLine summary={holding.pnl} label="" /> : <span className="muted">—</span>}
                    </span>
                    <span className="expand-mark">{isOpen ? "−" : "+"}</span>
                  </button>
                  {isOpen && (
                    <HoldingDetails
                      holding={holding}
                      onEditManual={openManualEdit}
                      onDeleteManual={deleteManual}
                    />
                  )}
                </article>
              );
            })}
          </div>
        ) : portfolio ? (
          <EmptyState title="No matching holdings">
            {portfolio.position_count
              ? "Nothing matches. Try another filter or search term."
              : "Connect a broker, import a statement, or add a holding by hand. "}
            {!portfolio.position_count && <Link to="/connections">Add a source</Link>}
          </EmptyState>
        ) : (
          <div className="holdings-loading">Loading your consolidated portfolio…</div>
        )}
      </section>

      {manualEditor && (
        <div className="modal-backdrop" onMouseDown={() => setManualEditor(null)}>
          <form
            className="modal manual-position-modal"
            onSubmit={submitManual}
            onMouseDown={(event) => event.stopPropagation()}
          >
            <div>
              <p className="eyebrow">Your holding</p>
              <h2>{manualEditor.id ? "Edit holding" : "Add a holding"}</h2>
              <p className="muted manual-position-intro">
                Choose your asset and enter what you bought.
              </p>
            </div>
            <div className="manual-position-grid">
              <AssetPicker value={selectedAsset} assets={manualAssets} onChange={(asset) => {
                setSelectedAsset(asset);
                if (asset) purchasePriceInput.current?.focus();
              }} />
              <label>
                Purchase price <small className="label-hint">per unit</small>
                <span className="manual-price-input">
                  <input
                    name="average_price"
                    aria-label="Purchase price per unit"
                    ref={purchasePriceInput}
                    type="number"
                    min="0.00000001"
                    step="any"
                    defaultValue={manualEditor.source?.average_price ?? ""}
                    placeholder="100.00"
                    required
                  />
                  <select name="currency" aria-label="Purchase price currency"
                    defaultValue={manualEditor.source?.currency ?? "EUR"}>
                    {[...new Set(["EUR", "USD", "GBP", "CHF", "CZK", "PLN", manualEditor.source?.currency])]
                      .filter((code): code is string => Boolean(code))
                      .map((code) => <option key={code} value={code}>{code}</option>)}
                  </select>
                </span>
              </label>
              <label>
                Quantity
                <input
                  name="quantity"
                  type="number"
                  min="0.0000000001"
                  step="any"
                  defaultValue={manualEditor.source?.quantity ?? ""}
                  placeholder="2.5"
                  required
                />
              </label>
              <label className="manual-wide-field">
                Note <small className="label-hint">optional</small>
                <textarea
                  name="note"
                  defaultValue={manualEditor.source?.note ?? ""}
                  placeholder="Anything you want to remember about this holding"
                  maxLength={2000}
                  rows={3}
                />
              </label>
            </div>
            <p className="manual-value-note">
              Adding the same asset again combines it into one holding. Prices update
              automatically; if no price is found, we show what you paid.
            </p>
            {manualError && <p className="connection-error" role="alert">{manualError}</p>}
            <div className="button-row">
              <button type="button" className="text-button" onClick={() => setManualEditor(null)}>
                Cancel
              </button>
              <button type="submit" className="primary" disabled={savingManual || !selectedAsset}>
                {savingManual ? "Saving…" : manualEditor.id ? "Save changes" : "Add holding"}
              </button>
            </div>
          </form>
        </div>
      )}
    </>
  );
}
