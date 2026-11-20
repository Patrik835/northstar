import { useEffect, useId, useMemo, useState } from "react";
import { loadAssetCatalogue } from "./assetCatalogue";
import type { AssetCatalogue } from "./assetCatalogue";

export type AssetOption = {
  ticker: string;
  name: string;
  asset_type: "stock" | "etf" | "crypto";
  isin: string | null;
  catalogue_id?: string;
  rank?: number;
  country?: string | null;
};

// Retain the original ETF suggestions alongside the ranked stock/crypto catalogue.
const etfAssets: AssetOption[] = [
  ...[
    ["SPY", "SPDR S&P 500 ETF Trust", "US78462F1030"],
    ["VOO", "Vanguard S&P 500 ETF", "US9229083632"],
    ["VTI", "Vanguard Total Stock Market ETF", "US9229087690"],
    ["QQQ", "Invesco QQQ Trust", "US46090E1038"],
    ["VWCE", "Vanguard FTSE All-World UCITS ETF (Accumulating)", "IE00BK5BQT80"],
    ["VWRL", "Vanguard FTSE All-World UCITS ETF (Distributing)", "IE00B3RBWM25"],
    ["SXR8", "iShares Core S&P 500 UCITS ETF (Accumulating)", "IE00B5BMR087"],
    ["IWDA", "iShares Core MSCI World UCITS ETF (Accumulating)", "IE00B4L5Y983"],
  ].map(([ticker, name, isin]) => ({ ticker, name, isin, asset_type: "etf" as const })),
];

const key = (asset: AssetOption) => `${asset.asset_type}:${asset.isin ?? asset.ticker}`;

export function AssetPicker({ value, assets, onChange }: {
  value: AssetOption | null;
  assets: AssetOption[];
  onChange: (asset: AssetOption | null) => void;
}) {
  const id = useId();
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const [catalogue, setCatalogue] = useState<AssetCatalogue | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);

  useEffect(() => {
    let mounted = true;
    loadAssetCatalogue()
      .then((result) => { if (mounted) setCatalogue(result); })
      .catch(() => { if (mounted) setLoadError(true); })
      .finally(() => { if (mounted) setLoading(false); });
    return () => { mounted = false; };
  }, []);

  function retryCatalogue() {
    setLoading(true);
    setLoadError(false);
    void loadAssetCatalogue()
      .then(setCatalogue)
      .catch(() => setLoadError(true))
      .finally(() => setLoading(false));
  }

  const suggestions = useMemo(() => {
    const unique = new Map<string, AssetOption>();
    // Keep provider-verified portfolio metadata when the catalogue contains the same asset.
    const starters = [...(catalogue?.assets ?? []), ...etfAssets].filter((starter) => !assets.some((asset) =>
      asset.ticker === starter.ticker && asset.asset_type === starter.asset_type));
    for (const asset of [...assets, ...starters]) {
      if (!unique.has(key(asset))) unique.set(key(asset), asset);
    }
    const term = query.trim().toLowerCase();
    const score = (asset: AssetOption) => asset.ticker.toLowerCase() === term
      ? 0 : asset.ticker.toLowerCase().startsWith(term) ? 1 : 2;
    return [...unique.values()]
      .filter((asset) => `${asset.ticker} ${asset.name}`.toLowerCase().includes(term))
      .sort((a, b) => score(a) - score(b)
        || (a.rank ?? 0) - (b.rank ?? 0) || a.name.localeCompare(b.name))
      .slice(0, 8);
  }, [assets, query, catalogue]);

  function select(asset: AssetOption) {
    onChange(asset);
    setQuery("");
    setOpen(false);
  }

  if (value) return (
    <div className="manual-wide-field asset-picker">
      <span className="asset-field-label">Asset</span>
      <div className="asset-selected">
        <div><strong>{value.name}</strong><small>{value.ticker} · {value.asset_type.toUpperCase()}</small></div>
        <button type="button" className="text-button" onClick={() => {
          onChange(null);
          setQuery("");
          setActive(0);
          setOpen(true);
        }}>Change</button>
      </div>
    </div>
  );

  return (
    <div className="manual-wide-field asset-picker" onBlur={(event) => {
      if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false);
    }}>
      <label htmlFor={id}>Asset</label>
      <input
        id={id}
        role="combobox"
        aria-autocomplete="list"
        aria-expanded={open}
        aria-controls={`${id}-options`}
        aria-activedescendant={open && suggestions.length ? `${id}-option-${active}` : undefined}
        autoComplete="off"
        placeholder="Search a name or ticker, e.g. Bitcoin or BTC"
        value={query}
        autoFocus
        maxLength={100}
        onFocus={() => setOpen(true)}
        onChange={(event) => { setQuery(event.target.value); setActive(0); setOpen(true); }}
        onKeyDown={(event) => {
          if (event.key === "ArrowDown" || event.key === "ArrowUp") {
            event.preventDefault();
            setOpen(true);
            setActive((index) => suggestions.length
              ? (index + (event.key === "ArrowDown" ? 1 : -1) + suggestions.length) % suggestions.length : 0);
          } else if (event.key === "Enter") {
            event.preventDefault();
            if (open && suggestions[active]) select(suggestions[active]);
          } else if (event.key === "Escape") {
            event.preventDefault();
            setOpen(false);
          }
        }}
      />
      {open && (
        <div className="asset-suggestions" id={`${id}-options`} role="listbox" aria-label="Matching assets">
          {suggestions.map((asset, index) => (
            <button
              id={`${id}-option-${index}`}
              key={key(asset)}
              type="button"
              role="option"
              aria-selected={active === index}
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => select(asset)}
            >
              <strong>{asset.ticker}</strong>
              <span>{asset.name}<small>{asset.asset_type.toUpperCase()}{asset.country ? ` · ${asset.country}` : ""}{asset.isin ? ` · ${asset.isin}` : ""}</small></span>
            </button>
          ))}
          {loading && <p role="status">Loading assets…</p>}
          {!loading && !loadError && !suggestions.length && <p role="status">No matching asset. Try another name or ticker.</p>}
        </div>
      )}
      {loadError && <p className="asset-catalogue-hint" role="status">
        Asset list unavailable. <button type="button" className="text-button" onClick={retryCatalogue}>Try again</button>
      </p>}
      {catalogue && <p className="asset-catalogue-hint">3,000 stocks · 150 cryptocurrencies · Search by name or ticker</p>}
    </div>
  );
}
