import { useEffect, useState, type FormEvent } from "react";
import { api, ApiError, downloadApi } from "../../api/client";
import { useRouter } from "../../routing/Router";

type Profile = {
  goals: string | null;
  risk_tolerance: number | null;
  time_horizon_years: number | null;
};

export function ProfilePage() {
  const { navigate } = useRouter();
  const [profile, setProfile] = useState<Profile | null>(null);
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [exporting, setExporting] = useState(false);
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    api<Profile>("/profile").then(setProfile).catch(() => setError("Could not load profile"));
  }, []);

  async function saveProfile(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setError("");
    try {
      const result = await api<Profile>("/profile", {
        method: "PUT",
        body: JSON.stringify({
          goals: form.get("goals") || null,
          risk_tolerance: Number(form.get("risk_tolerance")),
          time_horizon_years: Number(form.get("time_horizon_years")),
        }),
      });
      setProfile(result);
      setStatus("Profile saved");
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "Could not save profile");
    }
  }

  async function exportData(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setExporting(true);
    setError("");
    try {
      await downloadApi("/auth/account/export", {
        method: "POST",
        body: JSON.stringify({ current_password: form.get("current_password") }),
      });
      setStatus("Account data downloaded");
      event.currentTarget.reset();
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "Could not export account data");
    } finally {
      setExporting(false);
    }
  }

  async function deleteAccount(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    if (!window.confirm("Permanently delete your Northstar account and all portfolio data?")) return;
    setDeleting(true);
    setError("");
    try {
      await api("/auth/account", {
        method: "DELETE",
        body: JSON.stringify({
          current_password: form.get("current_password"),
          confirmation: form.get("confirmation"),
        }),
      });
      navigate("/login", true);
      window.location.reload();
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "Could not delete the account");
      setDeleting(false);
    }
  }

  if (!profile && !error) return <p role="status">Loading profile…</p>;
  if (!profile) return <p className="error" role="alert">{error}</p>;

  return <>
    <header className="page-header"><div><p className="eyebrow">Personal settings</p><h1>Profile & data</h1></div></header>
    {status && <p className="notice" role="status">{status}</p>}
    {error && <p className="error" role="alert">{error}</p>}
    <div className="profile-settings-grid">
      <form className="panel settings-form" onSubmit={saveProfile}>
        <h2>Goals & risk</h2>
        <label>Investment goals<textarea name="goals" defaultValue={profile.goals ?? ""} placeholder="Retirement, long-term wealth growth…" rows={5}/></label>
        <label>Risk tolerance <span className="label-hint">1 cautious · 5 aggressive</span><input name="risk_tolerance" type="range" min="1" max="5" defaultValue={profile.risk_tolerance ?? 3}/></label>
        <label>Time horizon (years)<input name="time_horizon_years" type="number" min="1" max="100" defaultValue={profile.time_horizon_years ?? 10}/></label>
        <button className="primary">Save profile</button>
      </form>
      <section className="panel data-controls">
        <div><h2>Your data</h2><p className="muted">Download a portable copy of your account and portfolio.</p></div>
        <form onSubmit={exportData}>
          <label>Current password<input name="current_password" type="password" autoComplete="current-password" required /></label>
          <button className="secondary" disabled={exporting}>{exporting ? "Preparing…" : "Download my data"}</button>
        </form>
        <details className="danger-zone">
          <summary>Delete account</summary>
          <p>This permanently removes your account, connections, portfolio history, and conversations.</p>
          <form onSubmit={deleteAccount}>
            <label>Current password<input name="current_password" type="password" autoComplete="current-password" required /></label>
            <label>Type DELETE to confirm<input name="confirmation" autoComplete="off" pattern="DELETE" required /></label>
            <button className="danger-button" disabled={deleting}>{deleting ? "Deleting…" : "Delete permanently"}</button>
          </form>
        </details>
      </section>
    </div>
  </>;
}
