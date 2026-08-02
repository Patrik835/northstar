import { useEffect, useState, type FormEvent } from "react";
import { api } from "../../api/client";
import type { Broker, Connection, ConnectionGuide } from "../../api/types";

const names: Record<Broker, string> = { trading212: "Trading 212", etoro: "eToro", binance: "Binance" };
const statusLabels: Record<Connection["status"], string> = {
  pending: "Waiting for first sync",
  active: "Connected",
  limited: "Connected — history unavailable",
  error: "Needs attention",
  disabled: "Disabled",
};

export function ConnectionsPage() {
  const [connections, setConnections] = useState<Connection[]>([]);
  const [guides, setGuides] = useState<ConnectionGuide[]>([]);
  const [selected, setSelected] = useState<ConnectionGuide | null>(null);
  const [message, setMessage] = useState("");
  const [busyId, setBusyId] = useState<string | null>(null);

  async function refresh() { setConnections(await api<Connection[]>("/connections")); }
  useEffect(() => { void refresh(); api<ConnectionGuide[]>("/connections/guides").then(setGuides); }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selected) return;
    const data = new FormData(event.currentTarget);
    const credentials = Object.fromEntries(selected.credential_fields.map((field) => [field, String(data.get(field))]));
    try {
      const connection = await api<Connection>("/connections", { method: "POST", body: JSON.stringify({ broker: selected.broker, credentials }) });
      setSelected(null);
      setMessage(connection.status === "active" ? "Trading 212 connected and portfolio imported." : connection.status === "limited" ? "Trading 212 portfolio imported. History access is unavailable for this key." : "Credentials encrypted and saved. This source is waiting for synchronization support.");
      await refresh();
    } catch (reason) { setMessage(reason instanceof Error ? reason.message : "Could not save connection"); }
  }

  async function sync(connection: Connection) {
    setBusyId(connection.id); setMessage("");
    try {
      const result = await api<Connection>(`/connections/${connection.id}/sync`, { method: "POST" });
      setMessage(result.status === "active" ? "Trading 212 portfolio updated." : result.status === "limited" ? "Portfolio updated, but Trading 212 still denies history access." : result.last_error || "Synchronization failed.");
      await refresh();
    } catch (reason) { setMessage(reason instanceof Error ? reason.message : "Could not synchronize connection"); }
    finally { setBusyId(null); }
  }

  async function remove(connection: Connection) {
    if (!window.confirm(`Remove the ${names[connection.broker]} connection and its imported data?`)) return;
    setBusyId(connection.id); setMessage("");
    try {
      await api(`/connections/${connection.id}`, { method: "DELETE" });
      setMessage(`${names[connection.broker]} connection removed.`); await refresh();
    } catch (reason) { setMessage(reason instanceof Error ? reason.message : "Could not remove connection"); }
    finally { setBusyId(null); }
  }

  return <><header className="page-header"><div><p className="eyebrow">Data sources</p><h1>Connections</h1></div></header>
    {message && <p className="notice">{message}</p>}
    <section className="connection-grid">{guides.map((guide) => { const current = connections.find((item) => item.broker === guide.broker); return <article className="panel source-card" key={guide.broker}><div className={`source-icon ${guide.broker}`}>{names[guide.broker][0]}</div><div className="source-content"><h2>{names[guide.broker]}</h2><p className="muted">{guide.security_notice}</p>{current ? <><div className="connection-state"><span className={`status ${current.status}`}>{statusLabels[current.status]}</span><span className="credential-hint">Key ending {current.credential_hint.replace("••••", "")}</span></div>{current.last_error && <p className={current.status === "limited" ? "connection-warning" : "connection-error"}>{current.last_error}</p>}{current.last_synced_at && <p className="sync-time">Last updated {new Date(current.last_synced_at).toLocaleString()}</p>}<div className="connection-actions">{current.broker === "trading212" && <button className="secondary" disabled={busyId === current.id} onClick={() => void sync(current)}>{busyId === current.id ? "Syncing…" : current.status === "error" ? "Try again" : "Sync now"}</button>}<button className="text-button danger" disabled={busyId === current.id} onClick={() => void remove(current)}>Remove</button></div></> : <button className="secondary" onClick={() => setSelected(guide)}>Connect</button>}</div></article>; })}</section>
    {selected && <div className="modal-backdrop" onMouseDown={() => setSelected(null)}><form className="modal connection-modal" onSubmit={submit} onMouseDown={(event) => event.stopPropagation()}><p className="eyebrow">Secure connection</p><h2>Connect {names[selected.broker]}</h2><div className="security-callout">{selected.security_notice}</div><section className="setup-guide"><h3>How to get your keys</h3><ol>{selected.setup_steps.map((step) => <li key={step}>{step}</li>)}</ol><a className="official-guide-link" href={selected.tutorial_url} target="_blank" rel="noreferrer">Broker screens look different? View the official guide <span>↗</span></a></section><div className="credential-fields"><h3>Enter your credentials</h3>{selected.credential_fields.map((field) => <label key={field}>{field.replaceAll("_", " ")}<input name={field} type="password" autoComplete="off" required /></label>)}</div><div className="button-row"><button type="button" className="text-button" onClick={() => setSelected(null)}>Cancel</button><button className="primary">Encrypt & save</button></div></form></div>}
  </>;
}
