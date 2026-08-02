import { useEffect, useRef, useState, type FormEvent } from "react";
import { ApiError, api } from "../../api/client";
import { Link } from "../../routing/Router";

type Message = { message: string };
type VerificationState = "working" | "verified" | "failed";

export function VerifyEmailPage() {
  const [state, setState] = useState<VerificationState>("working");
  const [message, setMessage] = useState("Verifying your email address…");
  const [resendMessage, setResendMessage] = useState("");
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    const token = new URLSearchParams(window.location.search).get("token");
    if (!token) {
      setState("failed");
      setMessage("This verification link is missing its token.");
      return;
    }
    api<Message>("/auth/verify-email", {
      method: "POST",
      body: JSON.stringify({ token }),
    })
      .then((response) => {
        setState("verified");
        setMessage(response.message);
      })
      .catch((reason: unknown) => {
        setState("failed");
        setMessage(reason instanceof ApiError ? reason.message : "Verification failed");
      });
  }, []);

  async function resend(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    try {
      const response = await api<Message>("/auth/resend-verification", {
        method: "POST",
        body: JSON.stringify({ email: data.get("email") }),
      });
      setResendMessage(response.message);
    } catch (reason) {
      setResendMessage(reason instanceof ApiError ? reason.message : "Could not resend email");
    }
  }

  return (
    <main className="verification-shell">
      <section className="login-card verification-card">
        <span className={`verification-mark ${state}`}>{state === "verified" ? "✓" : state === "failed" ? "!" : "…"}</span>
        <p className="eyebrow">Email verification</p>
        <h1>{state === "verified" ? "You’re verified" : state === "failed" ? "Link unavailable" : "One moment"}</h1>
        <p className="muted">{message}</p>
        {state === "verified" && <Link className="primary auth-link-button" to="/login">Continue to sign in</Link>}
        {state === "failed" && <form className="resend-form" onSubmit={resend}><label>Email<input name="email" type="email" required /></label><button className="secondary">Send a new link</button>{resendMessage && <p className="notice">{resendMessage}</p>}</form>}
      </section>
    </main>
  );
}

