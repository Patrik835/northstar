import { useEffect, useState, type FormEvent } from "react";
import { ApiError } from "../../api/client";
import { Link, useRouter } from "../../routing/Router";
import { useAuth } from "./AuthContext";

export function LoginPage() {
  const { user, login } = useAuth();
  const { navigate } = useRouter();
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (user) navigate("/", true);
  }, [navigate, user]);

  if (user) return null;

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    setSubmitting(true);
    setError("");
    try {
      await login(String(data.get("username")), String(data.get("password")));
      navigate("/");
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "Unable to sign in");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="login-shell">
      <section className="login-copy">
        <p className="eyebrow">Northstar</p>
        <h1>Every investment.<br />One clear view.</h1>
        <p>Private portfolio intelligence for the decisions that compound.</p>
      </section>
      <form className="login-card" onSubmit={submit}>
        <div><p className="eyebrow">Welcome back</p><h2>Sign in</h2></div>
        <label>Username<input name="username" autoComplete="username" required /></label>
        <label>Password<input name="password" type="password" autoComplete="current-password" minLength={8} required /></label>
        {error && <p className="error" role="alert">{error}</p>}
        <button className="primary" disabled={submitting}>{submitting ? "Signing in…" : "Sign in"}</button>
        <p className="fine-print">New to Northstar? <Link to="/register">Create an account</Link></p>
      </form>
    </main>
  );
}
