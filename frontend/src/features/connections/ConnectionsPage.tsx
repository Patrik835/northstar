import { useEffect, useMemo, useState, type FormEvent } from "react";
import { api } from "../../api/client";
import type {
  Broker,
  Connection,
  ConnectionGuide,
  StatementImportResult,
} from "../../api/types";
import { relativeTime } from "../../components/FreshnessStatus";
import { brokerName } from "../../domain/brokers";
import { Link } from "../../routing/Router";
import { SourceDialog, SourceMark } from "./SourceDialog";

function statusLabel(connection: Connection, isCsv: boolean) {
  if (connection.status === "pending") return "Updating…";
  if (connection.status === "error") return "Needs your attention";
  if (connection.status === "disabled") return "Paused";
  if (connection.status === "limited") return isCsv ? "Imported (some values estimated)" : "Connected (some history missing)";
  if (isCsv) return connection.is_stale ? "Import a newer file to refresh" : "Imported";
  return connection.is_stale ? "Not up to date" : "Up to date";
}

function statusTone(connection: Connection) {
  if (connection.status === "error") return "error";
  if (connection.status === "pending" || connection.status === "limited" || connection.is_stale) return "limited";
  return "active";
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
  const [success, setSuccess] = useState(false);
  // Deep link from onboarding: /connections?type=csv shows file imports first.
  const [firstGroup] = useState<"api" | "csv">(() =>
    new URLSearchParams(window.location.search).get("type") === "csv" ? "csv" : "api",
  );

  async function refresh() {
    setConnections(await api<Connection[]>("/connections"));
  }

  useEffect(() => {
    void refresh();
    api<ConnectionGuide[]>("/connections/guides").then(setGuides);
  }, []);

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
      setSuccess(connection.status !== "error");
      setMessage(
        connection.status === "active"
          ? wasReconnect
            ? `${brokerName(connection.broker)} is working again and your portfolio is updated.`
            : `${brokerName(connection.broker)} is connected and your investments are imported.`
          : connection.status === "limited"
            ? `${brokerName(connection.broker)} is connected. Some older history isn't available from this broker.`
            : connection.last_error || "Saved, but the connection needs your attention.",
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
      setSuccess(true);
      setMessage(
        `Imported ${result.positions_imported} ${fileImport.holding_label}${
          result.positions_imported === 1 ? "" : "s"
        } and ${result.transactions_added} new transaction${
          result.transactions_added === 1 ? "" : "s"
        }.${result.duplicates_skipped ? ` ${result.duplicates_skipped} already imported ${
          result.duplicates_skipped === 1 ? "entry was" : "entries were"
        } skipped.` : ""}${
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
    setSuccess(false);
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
    setSuccess(false);
    try {
      const results = await api<Connection[]>("/connections/sync-all", {
        method: "POST",
      });
      const failed = results.filter((connection) => connection.status === "error").length;
      setMessage(
        results.length === 0
          ? "There are no automatic sources to update."
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
    setSuccess(false);
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
            Where your investments come from. Connect a broker once and it updates by itself,
            or upload the statement file your broker gives you.
          </p>
        </div>
      </header>

      {message && (
        <p className={`notice${success ? " success-notice" : ""}`} role="status">
          {message}
          {success && <> <Link to="/holdings">See your holdings →</Link></>}
        </p>
      )}

      {connections.length > 0 && (
        <section className="connected-section">
          <div className="section-heading">
            <div>
              <p className="eyebrow">Your data</p>
              <h2>Your sources</h2>
            </div>
            <div className="section-heading-actions">
              <span className="connection-count">{connections.length}</span>
              <button
                className="secondary"
                disabled={busyId !== null || automaticConnectionCount === 0}
                title={
                  automaticConnectionCount > 0
                    ? "Fetch the latest data from every connected broker"
                    : "No automatically updating sources yet"
                }
                onClick={() => void syncAll()}
              >
                {busyId === "all" ? "Updating…" : "Update all now"}
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
                      <span className={`status ${statusTone(connection)}`}>
                        {statusLabel(connection, isCsv)}
                      </span>
                    </div>
                    <small>
                      {isCsv ? "File import" : `Key ${connection.credential_hint.replace("••••", "ending ")}`}
                      {" · "}
                      {connection.last_successful_sync_at
                        ? `${isCsv ? "Imported" : "Updated"} ${relativeTime(connection.last_successful_sync_at)}`
                        : "Not updated yet"}
                    </small>
                    {connection.last_error && (
                      <p className={connection.status === "error" ? "connection-error" : "connection-warning"}>
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
                        Upload newer file
                      </button>
                    ) : connection.status === "error" && guide ? (
                      <button
                        className="primary"
                        disabled={isBusy}
                        onClick={() => openReconnect(connection, guide)}
                      >
                        Fix connection
                      </button>
                    ) : (
                      <button
                        className="secondary"
                        disabled={isBusy}
                        onClick={() => void sync(connection)}
                      >
                        {busyId === connection.id ? "Updating…" : "Update now"}
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
                              Replace API key
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

      {(firstGroup === "api" ? (["api", "csv"] as const) : (["csv", "api"] as const)).map((group) => {
        const groupGuides = guides.filter((guide) => guide.connection_type === group);
        if (!groupGuides.length) return null;
        return (
          <section className="source-directory panel" key={group}>
            <div className="directory-header">
              <div>
                <p className="eyebrow">{group === "api" ? "Updates automatically" : "Upload a file"}</p>
                <h2>{group === "api" ? "Connect a broker" : "Import a statement"}</h2>
                <p className="muted directory-intro">
                  {group === "api"
                    ? "Create a read-only key in your broker's app and paste it here. We can never trade or withdraw."
                    : "For brokers without a connection: download your statement and upload it. Re-uploading is safe."}
                </p>
              </div>
            </div>
            <div className="source-catalog">
              {groupGuides.map((guide) => {
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
                    </div>
                    {current && guide.connection_type === "api" ? (
                      <span className="catalog-connected">Connected ✓</span>
                    ) : (
                      <button className={current ? "secondary" : "primary"} onClick={() => openSource(guide)}>
                        {current ? "Upload newer file" : guide.connection_type === "csv" ? "Import" : "Connect"}
                      </button>
                    )}
                  </article>
                );
              })}
            </div>
          </section>
        );
      })}

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
