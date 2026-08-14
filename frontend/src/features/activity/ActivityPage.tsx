import { useEffect, useMemo, useState } from "react";
import { api } from "../../api/client";
import type {
  ActivityResponse,
  Broker,
  TransactionType,
} from "../../api/types";
import { EmptyState } from "../../components/EmptyState";

const brokerLabels: Record<Broker, string> = {
  trading212: "Trading 212",
  trading212_crypto: "Trading 212 Crypto",
  etoro: "eToro",
  binance: "Binance",
  xtb: "XTB",
};
const activityLabels: Record<TransactionType, string> = {
  buy: "Buy",
  sell: "Sell",
  dividend: "Dividend",
  deposit: "Deposit",
  withdrawal: "Withdrawal",
  fee: "Fee",
  other: "Other",
};
const allBrokers = Object.keys(brokerLabels) as Broker[];
type ActivityGroup = "trade" | "dividend";
const activityGroups: Array<[ActivityGroup, string]> = [
  ["trade", "Buy / Sell"],
  ["dividend", "Dividend"],
];
const eur = new Intl.NumberFormat("en-IE", { style: "currency", currency: "EUR" });
const number = new Intl.NumberFormat("en-IE", { maximumFractionDigits: 8 });

function nativeAmount(value: string, currency: string) {
  try {
    return new Intl.NumberFormat("en-IE", {
      style: "currency", currency, maximumFractionDigits: 8,
    }).format(Number(value));
  } catch {
    return `${number.format(Number(value))} ${currency}`;
  }
}

function activityTotal(total: ActivityResponse["summary"]["bought"]) {
  const amounts = total.native_values.map((item) =>
    nativeAmount(item.value, item.currency));
  if (Number(total.value_eur) !== 0 || amounts.length === 0) {
    amounts.unshift(eur.format(Number(total.value_eur)));
  }
  return amounts.join(" + ");
}

export function ActivityPage() {
  const [result, setResult] = useState<ActivityResponse | null>(null);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [broker, setBroker] = useState<Broker | "">("");
  const [type, setType] = useState<ActivityGroup | "">("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [offset, setOffset] = useState(0);

  const query = useMemo(() => {
    const params = new URLSearchParams({
      limit: "50", offset: String(offset), display_only: "true",
    });
    if (search.trim()) params.set("search", search.trim());
    if (broker) params.set("broker", broker);
    if (type) params.set("activity_group", type);
    if (dateFrom) params.set("date_from", dateFrom);
    if (dateTo) params.set("date_to", dateTo);
    return params.toString();
  }, [broker, dateFrom, dateTo, offset, search, type]);

  useEffect(() => {
    const timeout = window.setTimeout(() => {
      api<ActivityResponse>(`/activity?${query}`)
        .then((data) => {
          setResult(data);
          setError("");
        })
        .catch((reason: Error) => setError(reason.message));
    }, 180);
    return () => window.clearTimeout(timeout);
  }, [query]);

  function resetAnd(action: () => void) {
    setOffset(0);
    action();
  }

  function changePage(nextOffset: number) {
    setOffset(nextOffset);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  const periodLabel = dateFrom && dateTo
    ? `${new Date(`${dateFrom}T00:00:00`).toLocaleDateString()} – ${new Date(`${dateTo}T00:00:00`).toLocaleDateString()}`
    : dateFrom ? `From ${new Date(`${dateFrom}T00:00:00`).toLocaleDateString()}`
      : dateTo ? `Through ${new Date(`${dateTo}T00:00:00`).toLocaleDateString()}` : "All time";

  return (
    <>
      <header className="page-header activity-header">
        <div>
          <p className="eyebrow">Portfolio ledger</p>
          <h1>Activity</h1>
          <p className="page-intro">
            Buys, sells, and dividends from every connected source.
          </p>
        </div>
        <span className="as-of">{result ? `${result.total} matching events` : "Loading…"}</span>
      </header>
      {error && <p className="error">{error}</p>}
      <section className="panel activity-panel">
        <div className="activity-filters">
          <label className="activity-search">
            <span>Search</span>
            <input
              value={search}
              onChange={(event) => resetAnd(() => setSearch(event.target.value))}
              placeholder="Instrument or ticker…"
            />
          </label>
          <label>
            <span>Source</span>
            <select
              value={broker}
              onChange={(event) =>
                resetAnd(() => setBroker(event.target.value as Broker | ""))
              }
            >
              <option value="">All sources</option>
              {allBrokers.map((value) => (
                <option value={value} key={value}>{brokerLabels[value]}</option>
              ))}
            </select>
          </label>
          <label>
            <span>Type</span>
            <select
              value={type}
              onChange={(event) =>
                resetAnd(() => setType(event.target.value as ActivityGroup | ""))
              }
            >
              <option value="">All activity</option>
              {activityGroups.map(([value, label]) => (
                <option value={value} key={value}>{label}</option>
              ))}
            </select>
          </label>
          <label>
            <span>From</span>
            <input
              type="date"
              value={dateFrom}
              onChange={(event) => resetAnd(() => setDateFrom(event.target.value))}
            />
          </label>
          <label>
            <span>To</span>
            <input
              type="date"
              value={dateTo}
              onChange={(event) => resetAnd(() => setDateTo(event.target.value))}
            />
          </label>
        </div>
        {result && (
          <div className="activity-period-summary">
            <div className="period-summary-heading">
              <span>{dateFrom || dateTo ? "Selected period" : "Activity totals"}</span>
              <small>{periodLabel}</small>
            </div>
            {(
              [
                ["Bought", result.summary.bought],
                ["Sold", result.summary.sold],
                ["Dividends", result.summary.dividends],
              ] as const
            ).map(([label, total]) => (
              <div className="period-summary-value" key={label}>
                <span>{label}</span>
                <strong>{activityTotal(total)}</strong>
                <small>
                  {total.event_count} event{total.event_count === 1 ? "" : "s"}
                  {total.missing_eur_count > 0 && (
                    <em title={`${total.missing_eur_count} event(s) are shown in their original currency because no historical EUR conversion is stored`}>
                      original currency
                    </em>
                  )}
                  {total.estimated_eur_count > 0 && (
                    <em title={`${total.estimated_eur_count} event(s) use the latest available rate because no rate was stored for the transaction date`}>
                      estimated FX
                    </em>
                  )}
                </small>
              </div>
            ))}
          </div>
        )}
        {result?.items.length ? (
          <>
            <div className="activity-table">
              <div className="activity-table-head">
                <span>Date</span><span>Activity</span><span>Instrument</span>
                <span>Source</span><span>Quantity</span><span>Value</span>
              </div>
              {result.items.map((item) => (
                <article className="activity-row" key={item.id}>
                  <time dateTime={item.executed_at}>
                    {new Date(item.executed_at).toLocaleDateString(undefined, {
                      day: "numeric", month: "short", year: "numeric",
                    })}
                  </time>
                  <span className={`activity-kind ${item.transaction_type}`}>
                    {activityLabels[item.transaction_type]}
                  </span>
                  <span className="activity-instrument">
                    <strong>{item.symbol}</strong><small>{item.name}</small>
                  </span>
                  <span>{brokerLabels[item.broker]}</span>
                  <span>{item.quantity === null ? "—" : number.format(Number(item.quantity))}</span>
                  <span className="activity-value">
                    <strong>
                      {item.value_eur === null
                        ? `${number.format(Number(item.value))} ${item.currency}`
                        : eur.format(Number(item.value_eur))}
                    </strong>
                    {item.value_eur !== null && item.currency !== "EUR" && (
                      <small>
                        {number.format(Number(item.value))} {item.currency}
                        {item.is_estimated_fx ? " · estimated FX" : ""}
                      </small>
                    )}
                  </span>
                </article>
              ))}
            </div>
            <div className="activity-pagination">
              <button
                className="secondary"
                disabled={offset === 0}
                onClick={() => changePage(Math.max(0, offset - 50))}
              >Previous</button>
              <span>{offset + 1}–{Math.min(offset + 50, result.total)} of {result.total}</span>
              <button
                className="secondary"
                disabled={offset + 50 >= result.total}
                onClick={() => changePage(offset + 50)}
              >Next</button>
            </div>
          </>
        ) : result ? (
          <EmptyState title="No matching activity">
            Try widening the dates or clearing a filter.
          </EmptyState>
        ) : (
          <div className="holdings-loading">Loading portfolio activity…</div>
        )}
      </section>
    </>
  );
}
