import { useEffect, useMemo, useState, type FormEvent } from "react";
import { api } from "../../api/client";
import type {
  Broker,
  Connection,
  ConnectionGuide,
  StatementImportResult,
} from "../../api/types";
import { brokerName } from "../../domain/brokers";
import { SourceDialog, SourceMark } from "./SourceDialog";

type SourceFilter = "all" | "connected" | "api" | "csv";

function statusLabel(connection: Connection, isCsv: boolean) {
  if (connection.status === "pending") return "Waiting for data";
  if (connection.status === "active") return connection.is_stale ? "Connected" : "Up to date";
  if (connection.status === "limited") {
    return isCsv ? "Imported with estimates" : "Connected with limitations";
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
  const [modalMessage, setModalMessage] = useState("");
  const [busyId, setBusyId] = useState<string | null>(null);
  const [openMenuId, setOpenMenuId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<SourceFilter>(() => {
    // Deep link from onboarding: /connections?type=api or ?type=csv.
    const type = new URLSearchParams(window.location.search).get("type");
    return type === "api" || type === "csv" ? type : "all";
  });

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
        guide.display_name.toLowerCase().includes(needle) ||
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
    setModalMessage("");
  }

  function openSource(guide: ConnectionGuide) {
    setReconnecting(null);
    setSelected(guide);
    setModalMessage("");
  }

  function openReconnect(connection: Connection, guide: ConnectionGuide) {
    setOpenMenuId(null);
    setReconnecting(connection);
    setSelected(guide);
    setMessage("");
    setModalMessage("");
  }

  async function submitApi(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selected) return;
    const data = new FormData(event.currentTarget);
    const credentials = Object.fromEntries(
      selected.credential_fields.map((field) => [field, String(data.get(field) ?? "").trim()]),
    );
    if (Object.values(credentials).some((value) => !value)) {
      setModalMessage("Fill in every field to continue.");
      return;
    }
    const busyKey = reconnecting?.id ?? selected.broker;
    setMessage("");
    setModalMessage("");
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
            ? `${brokerName(connection.broker)} credentials replaced and portfolio updated.`
            : `${brokerName(connection.broker)} connected and portfolio imported.`
          : connection.status === "limited"
            ? wasReconnect
              ? `${brokerName(connection.broker)} credentials replaced; history access is limited.`
              : `${brokerName(connection.broker)} imported with limited history access.`
            : connection.last_error || "The connection was saved but needs attention.",
      );
      await refresh();
    } catch (reason) {
      setModalMessage(reason instanceof Error ? reason.message : "Could not save connection");
    } finally {
      setBusyId(null);
    }
  }

  async function submitCsv(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selected) return;
    const fileImport = selected.file_import;
    if (!fileImport) {
      setModalMessage("This import source is not configured correctly.");
      return;
    }
    const form = new FormData(event.currentTarget);
    const files = form
      .getAll("file")
      .filter((file): file is File => file instanceof File && file.size > 0);
    if (!files.length) {
      setModalMessage(fileImport.empty_file_message);
      return;
    }
    setModalMessage("");
    setBusyId(selected.broker);
    try {
      const result = await api<StatementImportResult>(fileImport.endpoint, {
        method: "POST",
        body: form,
      });
      closeModal();
      setMessage(
        `Imported ${result.positions_imported} ${fileImport.holding_label}${
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
      // Keep the dialog open so the error is visible next to the file the user chose.
      setModalMessage(reason instanceof Error ? reason.message : "Could not import the selected file");
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
          ? `${brokerName(result.broker)} portfolio updated.`
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
    if (!window.confirm(`Remove ${brokerName(connection.broker)} and all of its imported data?`)) {
      return;
    }
    setBusyId(connection.id);
    setMessage("");
    try {
      await api(`/connections/${connection.id}`, { method: "DELETE" });
      setMessage(`${brokerName(connection.broker)} source removed.`);
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
          <h1>Sources</h1>
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
                  <SourceMark
                    broker={connection.broker}
                    shortMark={guide?.short_mark}
                  />
                  <div className="connected-main">
                    <div>
                      <strong>{guide?.display_name ?? brokerName(connection.broker)}</strong>
                      <span className={`status ${connection.status}`}>
                        {statusLabel(connection, isCsv)}
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
                        aria-label={`More options for ${brokerName(connection.broker)}`}
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
                  <SourceMark broker={guide.broker} shortMark={guide.short_mark} />
                  <div className="catalog-copy">
                    <div>
                      <h3>{guide.display_name}</h3>
                      <span>{guide.category}</span>
                    </div>
                    <p>{guide.description}</p>
                    <small>
                      {guide.connection_type === "api"
                        ? `Automatic · ${guide.sync_frequency_label ?? "Scheduled"}`
                        : "Manual import"}
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
        <SourceDialog
          guide={selected}
          reconnecting={reconnecting}
          busy={busyId === (reconnecting?.id ?? selected.broker)}
          error={modalMessage}
          onClose={closeModal}
          onSubmit={selected.connection_type === "csv" ? submitCsv : submitApi}
        />
      )}
    </>
  );
}
