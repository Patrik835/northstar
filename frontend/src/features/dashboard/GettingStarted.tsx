import { Link } from "../../routing/Router";

const steps = [
  {
    to: "/connections?type=api",
    title: "Connect a broker",
    body: "Trading 212, Binance, Bybit, eToro or Interactive Brokers. Read-only keys; updates automatically.",
    action: "Connect",
  },
  {
    to: "/connections?type=csv",
    title: "Import a statement",
    body: "XTB, Trade Republic, Scalable Capital or Trading 212 Crypto. Upload the file your broker gives you.",
    action: "Import a file",
  },
  {
    to: "/holdings?add=1",
    title: "Add a holding by hand",
    body: "Search any stock, ETF or crypto, then enter the quantity and what you paid.",
    action: "Add holding",
  },
];

/** Shown on Overview until the first investment exists, instead of empty charts. */
export function GettingStarted() {
  return (
    <section className="panel getting-started" aria-labelledby="getting-started-title">
      <p className="eyebrow">Get started</p>
      <h2 id="getting-started-title">Add your first investments</h2>
      <p className="muted">Pick whichever is easiest. You can combine all three later — matching investments are merged automatically.</p>
      <div className="getting-started-grid">
        {steps.map((step, index) => (
          <Link key={step.to} to={step.to} className="getting-started-card">
            <span className="getting-started-number">{index + 1}</span>
            <strong>{step.title}</strong>
            <span>{step.body}</span>
            <span className="getting-started-action">{step.action} →</span>
          </Link>
        ))}
      </div>
    </section>
  );
}
