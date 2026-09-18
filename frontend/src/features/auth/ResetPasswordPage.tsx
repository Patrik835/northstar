import { useState, type FormEvent } from "react";
import { api, ApiError } from "../../api/client";
import { Link } from "../../routing/Router";

export function ResetPasswordPage() {
  const token = new URLSearchParams(window.location.search).get("token") ?? "";
  const [message, setMessage] = useState("");
  const [error, setError] = useState(token ? "" : "This reset link is incomplete.");
  const [submitting, setSubmitting] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setSubmitting(true);
    setError("");
    try {
      const result = await api<{ message: string }>("/auth/password-reset/confirm", {
        method: "POST",
        body: JSON.stringify({
          token,
          new_password: form.get("password"),
          password_confirmation: form.get("password_confirmation"),
        }),
      });
      setMessage(result.message);
      event.currentTarget.reset();
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "Could not reset the password");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="verification-shell">
      <form className="login-card verification-card" onSubmit={submit}>
        <div className="verification-mark" aria-hidden="true">✓</div>
        <div><p className="eyebrow">Account recovery</p><h1>Choose a new password</h1></div>
        {!message && <>
          <label>New password<input name="password" type="password" autoComplete="new-password" minLength={12} required /></label>
          <label>Confirm password<input name="password_confirmation" type="password" autoComplete="new-password" minLength={12} required /></label>
          <button className="primary" disabled={submitting || !token}>{submitting ? "Saving…" : "Reset password"}</button>
        </>}
        {message && <p className="notice" role="status">{message}</p>}
        {error && <p className="error" role="alert">{error}</p>}
        <Link to="/login">Back to sign in</Link>
      </form>
    </main>
  );
}
