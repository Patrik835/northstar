import { useEffect, useMemo, useState, type FormEvent } from "react";
import { api } from "../../api/client";
import type {
  Broker,
  Connection,
  ConnectionGuide,
  StatementImportResult,
} from "../../api/types";

const names: Record<Broker, string> = {
  trading212: "Trading 212",
  trading212_crypto: "Trading 212 Crypto",
  etoro: "eToro",
  binance: "Binance",
  xtb: "XTB",
};

type SourceFilter = "all" | "connected" | "api" | "csv";

function sourceMark(broker: Broker) {
  if (broker === "trading212") return "T2";
  if (broker === "trading212_crypto") return "2C";
  if (broker === "binance") return "BN";
  if (broker === "xtb") return "XT";
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
  const [reconnecting, setReconnecting] = useState<Connection | null>(null);
  const [message, setMessage] = useState("");
  const [busyId, setBusyId] = useState<string | null>(null);
  const [openMenuId, setOpenMenuId] = useState<string | null>(null);
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

  const automaticConnectionCount = useMemo(
    () =>
      connections.filter((connection) =>
        guides.some(
          (guide) =>
            guide.broker === connection.broker && guide.connection_type === "api",
        ),
      ).length,
    [connections, guides],
  );

  function closeModal() {
    setSelected(null);
    setReconnecting(null);
  }

  function openSource(guide: ConnectionGuide) {
    setReconnecting(null);
    setSelected(guide);
  }

  function openReconnect(connection: Connection, guide: ConnectionGuide) {
    setOpenMenuId(null);
    setReconnecting(connection);
    setSelected(guide);
    setMessage("");
  }

  async function submitApi(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selected) return;
    const data = new FormData(event.currentTarget);
    const credentials = Object.fromEntries(
      selected.credential_fields.map((field) => [field, String(data.get(field))]),
    );
    const busyKey = reconnecting?.id ?? selected.broker;
    setBusyId(busyKey);
    try {
      const connection = reconnecting
        ? await api<Connection>(`/connections/${reconnecting.id}/credentials`, {
            method: "PUT",
            body: JSON.stringify({ credentials }),
          })
        : await api<Connection>("/connections", {
            method: "POST",
            body: JSON.stringify({ broker: selected.broker, credentials }),
          });
      const wasReconnect = reconnecting !== null;
      closeModal();
      setMessage(
        connection.status === "active"
          ? wasReconnect
            ? `${names[connection.broker]} credentials replaced and portfolio updated.`
            : `${names[connection.broker]} connected and portfolio imported.`
          : connection.status === "limited"
            ? wasReconnect
              ? `${names[connection.broker]} credentials replaced; history access is limited.`
              : `${names[connection.broker]} imported with limited history access.`
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
    const files = form
      .getAll("file")
      .filter((file): file is File => file instanceof File && file.size > 0);
    if (!files.length) {
      setMessage(
        selected.broker === "xtb"
          ? "Choose at least one XTB CSV or Excel report first."
          : "Choose the Trading 212 Crypto CSV export first.",
      );
      return;
    }
    setBusyId(selected.broker);
    try {
      const result = await api<StatementImportResult>(
        selected.broker === "xtb"
          ? "/connections/imports/xtb"
          : "/connections/imports/trading212-crypto",
        { method: "POST", body: form },
      );
      closeModal();
      const holdingLabel = selected.broker === "xtb" ? "holding" : "crypto holding";
      setMessage(
        `Imported ${result.positions_imported} ${holdingLabel}${
          result.positions_imported === 1 ? "" : "s"
        } and ${result.transactions_added} new transaction${
          result.transactions_added === 1 ? "" : "s"
        }. ${result.duplicates_skipped} duplicate${
          result.duplicates_skipped === 1 ? " was" : "s were"
        } skipped.${
          result.warnings.length
            ? ` ${result.warnings[0]}${
                result.warnings.length > 1
                  ? ` (${result.warnings.length - 1} more warning${
                      result.warnings.length === 2 ? "" : "s"
                    })`
                  : ""
              }`
            : ""
        }`,
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

  async function syncAll() {
    setBusyId("all");
    setOpenMenuId(null);
    setMessage("");
    try {
      const results = await api<Connection[]>("/connections/sync-all", {
        method: "POST",
      });
      const failed = results.filter((connection) => connection.status === "error").length;
      setMessage(
        results.length === 0
          ? "There are no automatic sources to synchronize."
          : failed > 0
            ? `${results.length - failed} source${
                results.length - failed === 1 ? "" : "s"
              } updated; ${failed} need${failed === 1 ? "s" : ""} attention.`
            : `All ${results.length} automatic source${
                results.length === 1 ? "" : "s"
              } updated.`,
      );
      await refresh();
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "Could not synchronize sources");
    } finally {
      setBusyId(null);
    }
  }

  async function remove(connection: Connection) {
    setOpenMenuId(null);
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
      </header>

      {message && <p className="notice">{message}</p>}

      {connections.length > 0 && (
        <section className="connected-section">
          <div className="section-heading">
            <div>
              <p className="eyebrow">Your data</p>
              <h2>Connected sources</h2>
            </div>
            <div className="section-heading-actions">
              <span className="connection-count">{connections.length}</span>
              <button
                className="secondary"
                disabled={busyId !== null || automaticConnectionCount === 0}
                title={
                  automaticConnectionCount > 0
                    ? "Synchronize all automatic sources"
                    : "No automatic sources connected"
                }
                onClick={() => void syncAll()}
              >
                {busyId === "all" ? "Syncing all…" : "Sync all now"}
              </button>
            </div>
          </div>
          <div className="connected-list">
            {connections.map((connection) => {
              const guide = guideFor(connection.broker);
              const isCsv = guide?.connection_type === "csv";
              const isBusy = busyId === connection.id || busyId === "all";
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
                        ? "File import"
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
                      <button
                        className="secondary"
                        disabled={isBusy}
                        onClick={() => guide && openSource(guide)}
                      >
                        Import newer file
                      </button>
                    ) : (
                      <button
                        className="secondary"
                        disabled={isBusy}
                        onClick={() => void sync(connection)}
                      >
                        {busyId === connection.id ? "Syncing…" : "Sync now"}
                      </button>
                    )}
                    <div
                      className="connection-menu"
                      onBlur={(event) => {
                        if (!event.currentTarget.contains(event.relatedTarget)) {
                          setOpenMenuId(null);
                        }
                      }}
                      onKeyDown={(event) => {
                        if (event.key === "Escape") setOpenMenuId(null);
                      }}
                    >
                      <button
                        className="icon-button"
                        aria-label={`More options for ${names[connection.broker]}`}
                        aria-haspopup="menu"
                        aria-expanded={openMenuId === connection.id}
                        title="Connection options"
                        disabled={isBusy}
                        onClick={() =>
                          setOpenMenuId((current) =>
                            current === connection.id ? null : connection.id,
                          )
                        }
                      >
                        ⋯
                      </button>
                      {openMenuId === connection.id && (
                        <div className="connection-menu-popover" role="menu">
                          {!isCsv && (
                            <button
                              role="menuitem"
                              disabled={!guide}
                              onClick={() => guide && openReconnect(connection, guide)}
                            >
                              Replace credentials
                            </button>
                          )}
                          <button
                            className="danger"
                            role="menuitem"
                            onClick={() => void remove(connection)}
                          >
                            Remove source
                          </button>
                        </div>
                      )}
                    </div>
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
                      {guide.connection_type === "api" ? "Automatic · 1–2 hours" : "Manual import"}
                    </small>
                  </div>
                  {current && guide.connection_type === "api" ? (
                    <span className="catalog-connected">Connected</span>
                  ) : (
                    <button className="secondary" onClick={() => openSource(guide)}>
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
        <div className="modal-backdrop" onMouseDown={closeModal}>
          <form
            key={reconnecting ? `replace:${reconnecting.id}` : `connect:${selected.broker}`}
            className={`modal connection-modal${reconnecting ? " reconnect-modal" : ""}`}
            onSubmit={selected.connection_type === "csv" ? submitCsv : submitApi}
            onMouseDown={(event) => event.stopPropagation()}
          >
            <div className="modal-source-heading">
              <span className={`compact-source-mark ${selected.broker}`}>
                {sourceMark(selected.broker)}
              </span>
              <div>
                <p className="eyebrow">
                  {selected.connection_type === "csv"
                    ? "Secure import"
                    : reconnecting
                      ? "Replace credentials"
                      : "Secure connection"}
                </p>
                <h2>{names[selected.broker]}</h2>
              </div>
            </div>
            {reconnecting ? (
              <p className="reconnect-note">
                Your current key stays active until the replacement is verified.
              </p>
            ) : (
              <div className="security-callout">{selected.security_notice}</div>
            )}
            {reconnecting && (
              <section
                className="setup-guide replacement-key-help"
                aria-label="Replacement key instructions"
              >
                <h3>Need help creating a replacement key?</h3>
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
            )}
            {!reconnecting && (
              <section className="setup-guide">
                <h3>
                  {selected.connection_type === "csv" ? "Prepare your export" : "Get your keys"}
                </h3>
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
            )}

            {selected.connection_type === "csv" ? (
              <label className="csv-dropzone">
                <span className="upload-mark">↑</span>
                <strong>
                  {selected.broker === "xtb"
                    ? "Select XTB reports"
                    : "Select Trading 212 Crypto CSV"}
                </strong>
                <small>
                  {selected.broker === "xtb"
                    ? "CSV or XLSX · select current positions and history together · overlapping reports are safe"
                    : "CSV only · maximum 10 MB · overlapping exports are safe"}
                </small>
                <input
                  name="file"
                  type="file"
                  accept={
                    selected.broker === "xtb"
                      ? ".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                      : ".csv,text/csv"
                  }
                  multiple={selected.broker === "xtb"}
                  required
                />
              </label>
            ) : (
              <div className="credential-fields">
                <h3>{reconnecting ? "New credentials" : "Enter your credentials"}</h3>
                {selected.credential_fields.map((field) => (
                  <label key={field}>
                    {selected.credential_labels[field] ?? field.replaceAll("_", " ")}
                    <input name={field} type="password" autoComplete="new-password" required />
                  </label>
                ))}
              </div>
            )}

            <div className="button-row">
              <button type="button" className="text-button" onClick={closeModal}>
                Cancel
              </button>
              <button
                className="primary"
                disabled={busyId === (reconnecting?.id ?? selected.broker)}
              >
                {busyId === (reconnecting?.id ?? selected.broker)
                  ? selected.connection_type === "csv"
                    ? "Importing…"
                    : reconnecting
                      ? "Replacing…"
                      : "Connecting…"
                  : selected.connection_type === "csv"
                    ? "Validate & import"
                    : reconnecting
                      ? "Validate & replace"
                      : "Encrypt & connect"}
              </button>
            </div>
          </form>
        </div>
      )}
    </>
  );
}
