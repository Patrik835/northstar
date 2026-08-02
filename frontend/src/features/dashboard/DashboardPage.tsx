import { useEffect, useState } from "react";
import { api } from "../../api/client";
import type { DashboardSummary } from "../../api/types";
import { EmptyState } from "../../components/EmptyState";
import { Link } from "../../routing/Router";

const money = new Intl.NumberFormat("en-IE", { style: "currency", currency: "EUR" });

export function DashboardPage() {
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { api<DashboardSummary>("/dashboard/summary").then(setSummary).catch((e: Error) => setError(e.message)); }, []);

  return (
    <>
      <header className="page-header"><div><p className="eyebrow">Portfolio overview</p><h1>Your financial picture</h1></div><span className="as-of">Values displayed in EUR</span></header>
      {error && <p className="error">{error}</p>}
      <section className="metric-grid">
        <article className="metric primary-metric"><span>Total portfolio</span><strong>{summary ? money.format(Number(summary.total_value_eur)) : "—"}</strong><small>Across all connected sources</small></article>
        <article className="metric"><span>Positions</span><strong>{summary?.positions_count ?? "—"}</strong><small>Current holdings</small></article>
        <article className="metric"><span>History</span><strong>Building</strong><small>From first connection date</small></article>
      </section>
      <section className="dashboard-grid">
        <article className="panel wide"><div className="panel-heading"><div><p className="eyebrow">Allocation</p><h2>By source</h2></div></div>
          {summary?.by_source.length ? <div className="allocation-list">{summary.by_source.map((item) => <div key={item.label}><span>{item.label}</span><progress max="100" value={item.percentage}/><strong>{item.percentage}%</strong></div>)}</div> : <EmptyState title="Connect your first account">Your aggregated portfolio will appear here after its first sync. <Link to="/connections">Add a connection</Link></EmptyState>}
        </article>
        <article className="panel"><p className="eyebrow">AI insight</p><h2>Portfolio review</h2><p className="muted">Enable the OpenAI feature flag to generate cached observations based on your holdings and risk profile.</p><div className="disclaimer">Informational and educational only—not financial advice.</div></article>
        <article className="panel"><p className="eyebrow">Market pulse</p><h2>Relevant news</h2><p className="muted">Holding-specific news and earnings dates will appear after Finnhub is enabled and positions are synced.</p></article>
      </section>
    </>
  );
}
