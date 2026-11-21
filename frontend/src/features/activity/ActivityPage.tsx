import { useEffect, useMemo, useState } from "react";
import { Loading } from "../../components/Loading";
import { api } from "../../api/client";
import type {
  ActivityResponse,
  Broker,
} from "../../api/types";
import { EmptyState } from "../../components/EmptyState";
import { CsvDownloadButton } from "../../components/CsvDownloadButton";
import { activityLabels } from "../../domain/activity";
import { brokerName, brokers } from "../../domain/brokers";
type ActivityGroup = "trade" | "dividend";
const activityGroups: Array<[ActivityGroup, string]> = [
  ["trade", "Bought / Sold"],
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

type Period = "3m" | "ytd" | "all" | "custom";
const periodOptions: Array<[Period, string]> = [
  ["3m", "Last 3 months"],
  ["ytd", "This year"],
  ["all", "All time"],
  ["custom", "Custom"],
];

function isoDate(value: Date) {
  return `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, "0")}-${String(value.getDate()).padStart(2, "0")}`;
}

function periodStart(period: Period): string {
  const now = new Date();
  if (period === "3m") return isoDate(new Date(now.getFullYear(), now.getMonth() - 3, now.getDate()));
  if (period === "ytd") return `${now.getFullYear()}-01-01`;
  return "";
}

export function ActivityPage() {
  const [result, setResult] = useState<ActivityResponse | null>(null);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [broker, setBroker] = useState<Broker | "">("");
  const [type, setType] = useState<ActivityGroup | "">("");
  const [period, setPeriod] = useState<Period>("3m");
  const [customFrom, setCustomFrom] = useState("");
  const [customTo, setCustomTo] = useState("");
  const [showFilters, setShowFilters] = useState(false);
  const [offset, setOffset] = useState(0);
  const dateFrom = period === "custom" ? customFrom : periodStart(period);
  const dateTo = period === "custom" ? customTo : "";
  const activeFilterCount = (broker ? 1 : 0) + (type ? 1 : 0);

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

  const exportPaths = useMemo(() => {
    const filters = new URLSearchParams();
    if (search.trim()) filters.set("search", search.trim());
    if (broker) filters.set("broker", broker);
    if (type) filters.set("activity_group", type);
    if (dateFrom) filters.set("date_from", dateFrom);
    if (dateTo) filters.set("date_to", dateTo);
    const incomeFilters = new URLSearchParams(filters);
    incomeFilters.delete("activity_group");
    const transactionQuery = filters.toString();
    const incomeQuery = incomeFilters.toString();
    return {
      transactions: `/exports/transactions.csv${transactionQuery ? `?${transactionQuery}` : ""}`,
      income: `/exports/income.csv${incomeQuery ? `?${incomeQuery}` : ""}`,
    };
  }, [broker, dateFrom, dateTo, search, type]);

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
          <p className="eyebrow">History</p>
          <h1>Activity</h1>
          <p className="page-intro">
            Everything you bought, sold or earned, from all your sources.
          </p>
        </div>
        <div className="page-header-actions activity-export-actions">
          <div className="csv-export-group">
            <CsvDownloadButton
              path={exportPaths.transactions}
              label="Download trades"
              disabled={!result}
            />
            <CsvDownloadButton
              path={exportPaths.income}
              label="Download dividends"
              disabled={!result}
            />
          </div>
          <span className="as-of">
            {result ? `${result.total} ${result.total === 1 ? "entry" : "entries"}` : "Loading…"}
          </span>
        </div>
      </header>
      {error && <p className="error">{error}</p>}
      <section className="panel activity-panel">
        <div className="activity-toolbar">
          <div className="activity-periods" role="group" aria-label="Period">
            {periodOptions.map(([value, label]) => (
              <button
                type="button"
                key={value}
                className={period === value ? "active" : ""}
                aria-pressed={period === value}
                onClick={() => resetAnd(() => setPeriod(value))}
              >
                {label}
              </button>
            ))}
          </div>
          <div className="activity-toolbar-right">
            <label className="activity-search">
              <span className="visually-hidden">Search</span>
              <input
                value={search}
                onChange={(event) => resetAnd(() => setSearch(event.target.value))}
                placeholder="Search by name or ticker…"
                aria-label="Search activity"
              />
            </label>
            <button
              type="button"
              className="secondary"
              aria-expanded={showFilters}
              onClick={() => setShowFilters((current) => !current)}
            >
              Filter{activeFilterCount ? ` (${activeFilterCount})` : ""}
            </button>
          </div>
        </div>
        {(showFilters || period === "custom") && (
          <div className="activity-filters">
            {showFilters && (
              <>
                <label>
                  <span>Source</span>
                  <select
                    value={broker}
                    onChange={(event) =>
                      resetAnd(() => setBroker(event.target.value as Broker | ""))
                    }
                  >
                    <option value="">All sources</option>
                    {brokers.map((value) => (
                      <option value={value} key={value}>{brokerName(value)}</option>
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
                    <option value="">Everything</option>
                    {activityGroups.map(([value, label]) => (
                      <option value={value} key={value}>{label}</option>
                    ))}
                  </select>
                </label>
              </>
            )}
            {period === "custom" && (
              <>
                <label>
                  <span>From</span>
                  <input
                    type="date"
                    value={customFrom}
                    onChange={(event) => resetAnd(() => setCustomFrom(event.target.value))}
                  />
                </label>
                <label>
                  <span>To</span>
                  <input
                    type="date"
                    value={customTo}
                    onChange={(event) => resetAnd(() => setCustomTo(event.target.value))}
                  />
                </label>
              </>
            )}
            {activeFilterCount > 0 && (
              <button
                type="button"
                className="text-button"
                onClick={() => resetAnd(() => { setBroker(""); setType(""); })}
              >
                Clear filters
              </button>
            )}
          </div>
        )}
        {result && (
          <div className="activity-period-summary">
            <div className="period-summary-heading">
              <span>Totals</span>
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
                      some in original currency
                    </em>
                  )}
                  {total.estimated_eur_count > 0 && (
                    <em title={`${total.estimated_eur_count} event(s) use the latest available rate because no rate was stored for the transaction date`}>
                      some converted at today's rate
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
                  <span>{brokerName(item.broker)}</span>
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
          <EmptyState title="Nothing here for this period">
            {period !== "all" ? (
              <button type="button" className="text-button" onClick={() => resetAnd(() => setPeriod("all"))}>
                Show all time
              </button>
            ) : "Try clearing a filter or search term."}
          </EmptyState>
        ) : (
          <Loading className="holdings-loading" label="Loading your activity…" />
        )}
      </section>
    </>
  );
}
