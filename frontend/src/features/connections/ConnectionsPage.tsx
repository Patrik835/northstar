import { useEffect, useMemo, useState, type FormEvent } from "react";
import { api } from "../../api/client";
import type {
  Broker,
  Connection,
  ConnectionGuide,
  CryptoCsvImportResult,
} from "../../api/types";

const names: Record<Broker, string> = {
  trading212: "Trading 212",
  trading212_crypto: "Trading 212 Crypto",
  etoro: "eToro",
  binance: "Binance",
};

type SourceFilter = "all" | "connected" | "api" | "csv";

function sourceMark(broker: Broker) {
  if (broker === "trading212") return "T2";
  if (broker === "trading212_crypto") return "2C";
  if (broker === "binance") return "BN";
  return "eT";
}

function statusLabel(connection: Connection) {
  if (connection.status === "pending") return "Waiting for data";
  if (connection.status === "active") return connection.is_stale ? "Connected" : "Up to date";
  if (connection.status === "limited") {
    return connection.broker === "trading212_crypto"
      ? "Imported with estimates"
      : "Connected with limitations";
  }
  if (connection.status === "error") return "Needs attention";
  return "Disabled";
}

function freshnessLabel(connection: Connection, isCsv: boolean) {
  if (connection.freshness_status === "never_synced") return "No successful sync";
  if (connection.freshness_status === "stale") return "Stale data";
  return isCsv ? "Imported data" : "Fresh data";
}

function timestamp(value: string | null) {
  return value ? new Date(value).toLocaleString() : "Not yet";
}

export function ConnectionsPage() {
  const [connections, setConnections] = useState<Connection[]>([]);
  const [guides, setGuides] = useState<ConnectionGuide[]>([]);
  const [selected, setSelected] = useState<ConnectionGuide | null>(null);
  const [message, setMessage] = useState("");
  const [busyId, setBusyId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<SourceFilter>("all");

  async function refresh() {
    setConnections(await api<Connection[]>("/connections"));
  }

  useEffect(() => {
    void refresh();
    api<ConnectionGuide[]>("/connections/guides").then(setGuides);
  }, []);

  const filteredGuides = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return guides.filter((guide) => {
      const current = connections.some((item) => item.broker === guide.broker);
      if (filter === "connected" && !current) return false;
      if (filter === "api" && guide.connection_type !== "api") return false;
      if (filter === "csv" && guide.connection_type !== "csv") return false;
      return (
        !needle ||
        names[guide.broker].toLowerCase().includes(needle) ||
        guide.category.toLowerCase().includes(needle) ||
        guide.description.toLowerCase().includes(needle)
      );
    });
  }, [connections, filter, guides, query]);

  async function submitApi(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selected) return;
    const data = new FormData(event.currentTarget);
    const credentials = Object.fromEntries(
      selected.credential_fields.map((field) => [field, String(data.get(field))]),
    );
    setBusyId(selected.broker);
    try {
      const connection = await api<Connection>("/connections", {
        method: "POST",
        body: JSON.stringify({ broker: selected.broker, credentials }),
      });
      setSelected(null);
      setMessage(
        connection.status === "active"
          ? `${names[connection.broker]} connected and portfolio imported.`
          : connection.status === "limited"
            ? `${names[connection.broker]} imported with limited history access.`
            : connection.last_error || "The connection was saved but needs attention.",
      );
      await refresh();
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "Could not save connection");
    } finally {
      setBusyId(null);
    }
  }

  async function submitCsv(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selected) return;
    const form = new FormData(event.currentTarget);
    const file = form.get("file");
    if (!(file instanceof File) || !file.size) {
      setMessage("Choose the Trading 212 Crypto CSV export first.");
      return;
    }
    setBusyId(selected.broker);
    try {
      const result = await api<CryptoCsvImportResult>(
        "/connections/imports/trading212-crypto",
        { method: "POST", body: form },
      );
      setSelected(null);
      setMessage(
        `Imported ${result.positions_imported} crypto holding${
          result.positions_imported === 1 ? "" : "s"
        } and ${result.transactions_added} new transaction${
          result.transactions_added === 1 ? "" : "s"
        }. ${result.duplicates_skipped} duplicate${
          result.duplicates_skipped === 1 ? " was" : "s were"
        } skipped.`,
      );
      await refresh();
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "Could not import the CSV");
    } finally {
      setBusyId(null);
    }
  }

  async function sync(connection: Connection) {
    setBusyId(connection.id);
    setMessage("");
    try {
      const result = await api<Connection>(`/connections/${connection.id}/sync`, {
        method: "POST",
      });
      setMessage(
        result.status === "active"
          ? `${names[result.broker]} portfolio updated.`
          : result.last_error || "Synchronization needs attention.",
      );
      await refresh();
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "Could not synchronize connection");
    } finally {
      setBusyId(null);
    }
  }

  async function remove(connection: Connection) {
    if (!window.confirm(`Remove ${names[connection.broker]} and all of its imported data?`)) {
      return;
    }
    setBusyId(connection.id);
    setMessage("");
    try {
      await api(`/connections/${connection.id}`, { method: "DELETE" });
      setMessage(`${names[connection.broker]} source removed.`);
      await refresh();
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "Could not remove source");
    } finally {
      setBusyId(null);
    }
  }

  function guideFor(broker: Broker) {
    return guides.find((guide) => guide.broker === broker);
  }

  return (
    <>
      <header className="page-header source-page-header">
        <div>
          <p className="eyebrow">Portfolio sources</p>
          <h1>Connections</h1>
          <p className="page-intro">
            Connect live accounts or import statements. Northstar keeps each source separate
            and combines matching investments in Holdings.
          </p>
        </div>
        <span className="as-of">
          {connections.length} active source{connections.length === 1 ? "" : "s"}
        </span>
      </header>

      {message && <p className="notice">{message}</p>}

      {connections.length > 0 && (
        <section className="connected-section">
          <div className="section-heading">
            <div>
              <p className="eyebrow">Your data</p>
              <h2>Connected sources</h2>
            </div>
            <span>{connections.length}</span>
          </div>
          <div className="connected-list">
            {connections.map((connection) => {
              const guide = guideFor(connection.broker);
              const isCsv = guide?.connection_type === "csv";
              return (
                <article className="connected-row" key={connection.id}>
                  <span className={`compact-source-mark ${connection.broker}`}>
                    {sourceMark(connection.broker)}
                  </span>
                  <div className="connected-main">
                    <div>
                      <strong>{names[connection.broker]}</strong>
                      <span className={`status ${connection.status}`}>
                        {statusLabel(connection)}
                      </span>
                      <span
                        className={`freshness ${connection.freshness_status}`}
                        title={
                          connection.stale_after
                            ? `Considered stale after ${timestamp(connection.stale_after)}`
                            : undefined
                        }
                      >
                        <span aria-hidden="true" />
                        {freshnessLabel(connection, isCsv)}
                      </span>
                    </div>
                    <small>
                      {isCsv
                        ? "CSV import"
                        : `Credential ${connection.credential_hint.replace("••••", "ending ")}`}
                    </small>
                    <div className="connection-timestamps">
                      <span>
                        {isCsv ? "Last import" : "Last successful sync"}: {timestamp(connection.last_successful_sync_at)}
                      </span>
                      {connection.status === "error" && connection.last_sync_attempt_at && (
                        <span>Last attempt: {timestamp(connection.last_sync_attempt_at)}</span>
                      )}
                    </div>
                    {connection.last_error && (
                      <p
                        className={
                          connection.status === "error"
                            ? "connection-error"
                            : "connection-warning"
                        }
                      >
                        {connection.last_error}
                      </p>
                    )}
                  </div>
                  <div className="connected-actions">
                    {isCsv ? (
                      <button className="secondary" onClick={() => guide && setSelected(guide)}>
                        Import newer CSV
                      </button>
                    ) : (
                      <button
                        className="secondary"
                        disabled={busyId === connection.id}
                        onClick={() => void sync(connection)}
                      >
                        {busyId === connection.id ? "Syncing…" : "Sync now"}
                      </button>
                    )}
                    <button
                      className="icon-button danger"
                      aria-label={`Remove ${names[connection.broker]}`}
                      title="Remove source"
                      disabled={busyId === connection.id}
                      onClick={() => void remove(connection)}
                    >
                      ×
                    </button>
                  </div>
                </article>
              );
            })}
          </div>
        </section>
      )}

      <section className="source-directory panel">
        <div className="directory-header">
          <div>
            <p className="eyebrow">Source directory</p>
            <h2>Add or manage a source</h2>
          </div>
          <label className="source-search">
            <span>Search sources</span>
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Broker, exchange, import…"
            />
          </label>
        </div>
        <div className="source-filter-row">
          {(
            [
              ["all", "All sources"],
              ["connected", "Connected"],
              ["api", "Automatic sync"],
              ["csv", "File imports"],
            ] as Array<[SourceFilter, string]>
          ).map(([value, label]) => (
            <button
              key={value}
              className={filter === value ? "active" : ""}
              onClick={() => setFilter(value)}
            >
              {label}
            </button>
          ))}
        </div>

        {filteredGuides.length ? (
          <div className="source-catalog">
            {filteredGuides.map((guide) => {
              const current = connections.find((item) => item.broker === guide.broker);
              return (
                <article className="source-catalog-item" key={guide.broker}>
                  <span className={`compact-source-mark ${guide.broker}`}>
                    {sourceMark(guide.broker)}
                  </span>
                  <div className="catalog-copy">
                    <div>
                      <h3>{names[guide.broker]}</h3>
                      <span>{guide.category}</span>
                    </div>
                    <p>{guide.description}</p>
                    <small>
                      {guide.connection_type === "api" ? "Automatic · 1–2 hours" : "Manual CSV"}
                    </small>
                  </div>
                  {current && guide.connection_type === "api" ? (
                    <span className="catalog-connected">Connected</span>
                  ) : (
                    <button className="secondary" onClick={() => setSelected(guide)}>
                      {current ? "Import again" : guide.connection_type === "csv" ? "Import" : "Connect"}
                    </button>
                  )}
                </article>
              );
            })}
          </div>
        ) : (
          <div className="directory-empty">
            <strong>No sources match</strong>
            <p>Try a different search or filter.</p>
          </div>
        )}
      </section>

      {selected && (
        <div className="modal-backdrop" onMouseDown={() => setSelected(null)}>
          <form
            className="modal connection-modal"
            onSubmit={selected.connection_type === "csv" ? submitCsv : submitApi}
            onMouseDown={(event) => event.stopPropagation()}
          >
            <div className="modal-source-heading">
              <span className={`compact-source-mark ${selected.broker}`}>
                {sourceMark(selected.broker)}
              </span>
              <div>
                <p className="eyebrow">
                  {selected.connection_type === "csv" ? "Secure import" : "Secure connection"}
                </p>
                <h2>{names[selected.broker]}</h2>
              </div>
            </div>
            <div className="security-callout">{selected.security_notice}</div>
            <section className="setup-guide">
              <h3>{selected.connection_type === "csv" ? "Prepare your export" : "How to get your keys"}</h3>
              <ol>
                {selected.setup_steps.map((step) => (
                  <li key={step}>{step}</li>
                ))}
              </ol>
              <a
                className="official-guide-link"
                href={selected.tutorial_url}
                target="_blank"
                rel="noreferrer"
              >
                View the official guide <span>↗</span>
              </a>
            </section>

            {selected.connection_type === "csv" ? (
              <label className="csv-dropzone">
                <span className="upload-mark">↑</span>
                <strong>Select Trading 212 Crypto CSV</strong>
                <small>CSV only · maximum 10 MB · overlapping exports are safe</small>
                <input name="file" type="file" accept=".csv,text/csv" required />
              </label>
            ) : (
              <div className="credential-fields">
                <h3>Enter your credentials</h3>
                {selected.credential_fields.map((field) => (
                  <label key={field}>
                    {selected.credential_labels[field] ?? field.replaceAll("_", " ")}
                    <input name={field} type="password" autoComplete="off" required />
                  </label>
                ))}
              </div>
            )}

            <div className="button-row">
              <button type="button" className="text-button" onClick={() => setSelected(null)}>
                Cancel
              </button>
              <button className="primary" disabled={busyId === selected.broker}>
                {busyId === selected.broker
                  ? selected.connection_type === "csv"
                    ? "Importing…"
                    : "Connecting…"
                  : selected.connection_type === "csv"
                    ? "Validate & import"
                    : "Encrypt & connect"}
              </button>
            </div>
          </form>
        </div>
      )}
    </>
  );
}
