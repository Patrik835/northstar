import { useState, type FormEvent } from "react";
import { ApiError, api } from "../../api/client";
import { Link, useRouter } from "../../routing/Router";

type Message = { message: string };

export function RegisterPage() {
  const { navigate } = useRouter();
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const username = String(data.get("username"));
    const email = String(data.get("email"));
    const password = String(data.get("password"));
    const passwordConfirmation = String(data.get("password_confirmation"));
    if (!/^[a-zA-Z0-9_.-]+$/.test(username)) {
      setError(
        "Username can only contain letters, numbers, dots, underscores, and hyphens",
      );
      return;
    }
    if (password !== passwordConfirmation) {
      setError("Passwords do not match");
      return;
    }
    setSubmitting(true);
    setError("");
    try {
      await api<Message>("/auth/register", {
        method: "POST",
        body: JSON.stringify({
          username,
          email,
          password,
          password_confirmation: passwordConfirmation,
        }),
      });
      form.reset();
      navigate(`/registration-pending?email=${encodeURIComponent(email)}`);
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "Unable to create account");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="login-shell">
      <section className="login-copy">
        <p className="eyebrow">Join Northstar</p>
        <h1>See the whole picture.</h1>
        <p>Create a private workspace for all your investments and goals.</p>
      </section>
      <form className="login-card register-card" onSubmit={submit}>
        <div><p className="eyebrow">Create account</p><h2>Start your portfolio</h2></div>
        <label>Username<input name="username" autoComplete="username" minLength={3} title="Use only letters, numbers, dots, underscores, and hyphens" required /></label>
        <label>Email<input name="email" type="email" autoComplete="email" required /></label>
        <label>Password<input name="password" type="password" autoComplete="new-password" minLength={12} required /></label>
        <label>Confirm password<input name="password_confirmation" type="password" autoComplete="new-password" minLength={12} required /></label>
        {error && <p className="error" role="alert">{error}</p>}
        <button className="primary" disabled={submitting}>{submitting ? "Creating account…" : "Create account"}</button>
        <p className="fine-print">Already registered? <Link to="/login">Sign in</Link></p>
      </form>
    </main>
  );
}
