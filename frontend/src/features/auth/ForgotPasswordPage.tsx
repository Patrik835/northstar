import { useState, type FormEvent } from "react";
import { api, ApiError } from "../../api/client";
import { Link } from "../../routing/Router";

export function ForgotPasswordPage() {
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setSubmitting(true);
    setError("");
    try {
      const result = await api<{ message: string }>("/auth/password-reset/request", {
        method: "POST",
        body: JSON.stringify({ email: form.get("email") }),
      });
      setMessage(result.message);
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "Could not request a reset link");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="verification-shell">
      <form className="login-card verification-card" onSubmit={submit}>
        <div className="verification-mark" aria-hidden="true">↗</div>
        <div><p className="eyebrow">Account recovery</p><h1>Reset your password</h1></div>
        <p className="muted">Enter your verified email address. We’ll send a one-time link.</p>
        <label>Email address<input name="email" type="email" autoComplete="email" required /></label>
        {message && <p className="notice" role="status">{message}</p>}
        {error && <p className="error" role="alert">{error}</p>}
        <button className="primary" disabled={submitting}>{submitting ? "Sending…" : "Send reset link"}</button>
        <Link to="/login">Back to sign in</Link>
      </form>
    </main>
  );
}
