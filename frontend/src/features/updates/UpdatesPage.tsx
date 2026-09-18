import { useEffect, useState, type FormEvent } from "react";
import { api } from "../../api/client";
import type { ContentSummary, NotificationPreference } from "../../api/types";
import { EmptyState } from "../../components/EmptyState";
import { Link } from "../../routing/Router";

function day(value: string) {
  return new Intl.DateTimeFormat("en-IE", { day: "numeric", month: "short" }).format(
    new Date(`${value}T12:00:00`),
  );
}

function ago(value: string) {
  const hours = Math.max(0, Math.floor((Date.now() - new Date(value).getTime()) / 3_600_000));
  if (hours < 1) return "Just now";
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

export function UpdatesPage() {
  const localInbox = ["localhost", "127.0.0.1"].includes(window.location.hostname)
    ? `http://${window.location.hostname}:8025`
    : null;
  const [content, setContent] = useState<ContentSummary | null>(null);
  const [preferences, setPreferences] = useState<NotificationPreference | null>(null);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const [newsTab, setNewsTab] = useState<"top" | "brief">("top");

  async function refresh() {
    const [nextContent, nextPreferences] = await Promise.all([
      api<ContentSummary>("/content?news_limit=20&event_limit=20&alert_limit=20"),
      api<NotificationPreference>("/content/preferences"),
    ]);
    setContent(nextContent);
    setPreferences(nextPreferences);
  }

  useEffect(() => {
    refresh().catch((reason: Error) => setError(reason.message));
  }, []);

  async function refreshMarketContent() {
    setRefreshing(true);
    setError("");
    try {
      setContent(await api<ContentSummary>("/content/refresh", { method: "POST" }));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not refresh updates");
    } finally {
      setRefreshing(false);
    }
  }

  async function readNews(id: string) {
    await api<void>(`/content/news/${id}/read`, { method: "POST" });
    setContent((current) => current ? {
      ...current,
      unread_news: Math.max(0, current.unread_news - (current.news.find((item) => item.id === id)?.is_read ? 0 : 1)),
      news: current.news.map((item) => item.id === id ? { ...item, is_read: true } : item),
    } : current);
  }

  async function readAlert(id: string) {
    await api<void>(`/content/alerts/${id}/read`, { method: "POST" });
    setContent((current) => current ? {
      ...current,
      unread_alerts: Math.max(0, current.unread_alerts - 1),
      alerts: current.alerts.map((item) => item.id === id
        ? { ...item, read_at: new Date().toISOString() }
        : item),
    } : current);
  }

  async function savePreferences(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!preferences) return;
    setSaved("");
    try {
      const next = await api<NotificationPreference>("/content/preferences", {
        method: "PUT",
        body: JSON.stringify({
          email_digest_enabled: preferences.email_digest_enabled,
          digest_frequency: preferences.digest_frequency,
        }),
      });
      setPreferences(next);
      setSaved("Saved");
    } catch (reason) {
      setSaved(reason instanceof Error ? reason.message : "Could not save preferences");
    }
  }

  async function setAccountEmail(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    setSaved("");
    try {
      const response = await api<{ message: string }>("/auth/account-email", {
        method: "POST",
        body: JSON.stringify({ email: data.get("email") }),
      });
      setSaved(response.message);
      await refresh();
    } catch (reason) {
      setSaved(reason instanceof Error ? reason.message : "Could not send verification");
    }
  }

  async function sendDigestNow() {
    setSaved("");
    try {
      await api<void>("/content/digest/send", { method: "POST" });
      setSaved("Digest sent");
      await refresh();
    } catch (reason) {
      setSaved(reason instanceof Error ? reason.message : "Could not send digest");
    }
  }

  return <>
    <header className="page-header compact-page-header">
      <div><p className="eyebrow">Updates</p><h1>What needs your attention</h1></div>
      <div className="page-header-actions">
        {content && <span className="as-of">{content.unread_alerts + content.unread_news} unread</span>}
        <button className="secondary compact-button" disabled={refreshing} onClick={() => void refreshMarketContent()}>{refreshing ? "Refreshing…" : "Refresh"}</button>
      </div>
    </header>
    {error && <p className="error">{error}</p>}

    {content?.alerts.some((item) => !item.read_at) && (
      <section className="panel attention-panel">
        <div className="panel-heading"><div><p className="eyebrow">Attention</p><h2>Portfolio alerts</h2></div></div>
        <div className="compact-update-list">
          {content.alerts.filter((item) => !item.read_at).map((item) => (
            <div className={`compact-update alert-${item.severity}`} key={item.id}>
              <span className="update-dot" />
              <div><strong>{item.title}</strong><small>{item.message}</small></div>
              <div className="update-actions">
                {item.source_url?.startsWith("/") && <Link to={item.source_url}>Open</Link>}
                <button className="text-button muted-action" onClick={() => void readAlert(item.id)}>Dismiss</button>
              </div>
            </div>
          ))}
        </div>
      </section>
    )}

    <section className="updates-grid">
      <article className="panel updates-panel">
        <div className="panel-heading news-panel-heading">
          <div><p className="eyebrow">Your portfolio</p><h2>Market updates</h2></div>
          <div className="updates-tabs" role="tablist" aria-label="Portfolio news view">
            <button className={newsTab === "top" ? "active" : ""} role="tab" aria-selected={newsTab === "top"} onClick={() => setNewsTab("top")}>Top news</button>
            <button className={newsTab === "brief" ? "active" : ""} role="tab" aria-selected={newsTab === "brief"} onClick={() => setNewsTab("brief")}>24h brief</button>
          </div>
        </div>
        {newsTab === "top" && (content?.news.length ? <div className="news-list">
            {content.news.map((item) => (
              <a
                className={`news-row ${item.is_read ? "read" : ""}`}
                href={item.url}
                target="_blank"
                rel="noreferrer"
                key={item.id}
                onClick={() => void readNews(item.id)}
              >
                <span>{item.ticker}</span>
                <div><strong>{item.headline}</strong><small>{item.source} · {ago(item.published_at)}</small></div>
              </a>
            ))}
          </div> : <EmptyState title="No relevant news yet">Today’s most important news for your holdings will appear here.</EmptyState>)}
        {newsTab === "brief" && (content?.brief?.highlights.length ? <div className="brief-list">
          <p className="brief-meta">Based on {content.brief.positions_count} holdings · updated {ago(content.brief.generated_at)}</p>
          {content.brief.highlights.map((highlight, index) => (
            <article className="brief-row" key={`${highlight.title}-${index}`}>
              <span className="brief-number">{index + 1}</span>
              <div>
                <div className="brief-title"><strong>{highlight.title}</strong><span>{highlight.tickers.join(" · ")}</span></div>
                <p>{highlight.summary}</p>
                <div className="brief-sources">
                  {highlight.news_ids.map((newsId) => {
                    const source = content.news.find((item) => item.id === newsId);
                    return source ? <a key={newsId} href={source.url} target="_blank" rel="noreferrer" onClick={() => void readNews(newsId)}>{source.source}</a> : null;
                  })}
                </div>
              </div>
            </article>
          ))}
        </div> : <EmptyState title="No 24-hour brief yet">Refresh after news is available to prepare a portfolio summary.</EmptyState>)}
      </article>

      <article className="panel updates-panel">
        <div className="panel-heading"><div><p className="eyebrow">Next 35 days</p><h2>Calendar</h2></div></div>
        {content?.events.length ? <div className="event-list">
          {content.events.map((item) => (
            <div className="event-row" key={item.id}>
              <time>{day(item.event_date)}</time>
              <div><strong>{item.title}</strong><small>{item.event_type === "earnings" ? "Earnings" : "Ex-dividend"}</small></div>
            </div>
          ))}
        </div> : <EmptyState title="No upcoming events">Held-company earnings and supported dividend dates will appear here.</EmptyState>}
      </article>
    </section>

    <details className="panel digest-settings">
      <summary>Email digest</summary>
      {preferences && !preferences.email_available && <form onSubmit={setAccountEmail}>
        <label>Email address
          <input name="email" type="email" defaultValue={preferences.email ?? ""} required />
        </label>
        <button className="secondary" type="submit">{preferences.email ? "Resend verification" : "Send verification"}</button>
        <span className="form-status">{preferences.email ? "Verify this address to enable digests." : "Add an address to enable digests."}</span>
      </form>}
      {preferences?.email_available && <form onSubmit={savePreferences}>
        <label className="toggle-line">
          <input
            type="checkbox"
            checked={preferences.email_digest_enabled}
            disabled={!preferences.email_available}
            onChange={(event) => setPreferences({ ...preferences, email_digest_enabled: event.target.checked })}
          />
          <span><strong>Send me a short digest</strong><small>Unread alerts, upcoming events, and relevant news only.</small></span>
        </label>
        {preferences.email_digest_enabled && <label>Frequency
          <select
            value={preferences.digest_frequency}
            onChange={(event) => setPreferences({ ...preferences, digest_frequency: event.target.value as "daily" | "weekly" })}
          ><option value="weekly">Weekly</option><option value="daily">Daily</option></select>
        </label>}
        <button className="secondary" type="submit">Save</button>
        {preferences.email_digest_enabled && <button className="text-button" type="button" onClick={() => void sendDigestNow()}>Send now</button>}
        {saved && <span className="form-status">{saved}</span>}
      </form>}
      {saved && !preferences?.email_available && <span className="form-status digest-email-status">{saved}{localInbox && <> · <a href={localInbox} target="_blank" rel="noreferrer">Open local inbox</a></>}</span>}
    </details>
  </>;
}
