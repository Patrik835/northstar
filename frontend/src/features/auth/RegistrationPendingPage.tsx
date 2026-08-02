import { Link } from "../../routing/Router";

export function RegistrationPendingPage() {
  const email = new URLSearchParams(window.location.search).get("email");

  return (
    <main className="verification-shell">
      <section className="login-card verification-card">
        <span className="verification-mark">✉</span>
        <p className="eyebrow">Almost there</p>
        <h1>Check your email</h1>
        <p className="muted">
          We sent a verification link{email ? <> to <strong>{email}</strong></> : ""}.
          Open it to activate your account before signing in.
        </p>
        <p className="fine-print">The link expires in 24 hours.</p>
        {window.location.hostname === "localhost" && (
          <a
            className="primary auth-link-button"
            href="http://localhost:8025"
            target="_blank"
            rel="noreferrer"
          >
            Open local email inbox
          </a>
        )}
        <Link to="/login">Back to sign in</Link>
      </section>
    </main>
  );
}
