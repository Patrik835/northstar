import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { Connection } from "../api/types";
import { brokerName } from "../domain/brokers";
import { Link } from "../routing/Router";

const REFRESH_MS = 5 * 60 * 1000;

export function relativeTime(value: string, now = Date.now()): string {
  const minutes = Math.max(0, Math.round((now - new Date(value).getTime()) / 60000));
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.round(hours / 24);
  return `${days} day${days === 1 ? "" : "s"} ago`;
}

/** One app-wide answer to "is my data up to date?", shown in the sidebar. */
export function FreshnessStatus() {
  const [connections, setConnections] = useState<Connection[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = () => api<Connection[]>("/connections")
      .then((value) => { if (!cancelled) setConnections(value); })
      .catch(() => undefined);
    void load();
    const timer = window.setInterval(load, REFRESH_MS);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, []);

  if (!connections) return null;
  if (connections.length === 0) {
    return (
      <Link to="/connections" className="freshness-status empty">
        <i aria-hidden="true" />No sources yet — add one
      </Link>
    );
  }

  const failing = connections.filter((connection) => connection.status === "error");
  if (failing.length) {
    return (
      <Link to="/connections" className="freshness-status attention">
        <i aria-hidden="true" />
        {failing.length === 1
          ? `${brokerName(failing[0].broker)} needs attention`
          : `${failing.length} sources need attention`}
      </Link>
    );
  }

  const latest = connections
    .map((connection) => connection.last_successful_sync_at)
    .filter((value): value is string => Boolean(value))
    .sort()
    .at(-1);
  return (
    <Link to="/connections" className="freshness-status ok">
      <i aria-hidden="true" />
      {latest ? `Updated ${relativeTime(latest)}` : "Waiting for first sync"}
    </Link>
  );
}
