import { useEffect, useState, type FormEvent } from "react";
import { Loading } from "../../components/Loading";
import { api, ApiError, downloadApi } from "../../api/client";
import { useRouter } from "../../routing/Router";

type Profile = {
  goals: string | null;
  risk_tolerance: number | null;
  time_horizon_years: number | null;
};

const riskChoices: Array<[number, string, string]> = [
  [1, "Very careful", "Avoid losses above all"],
  [2, "Careful", "Small swings only"],
  [3, "Balanced", "Some ups and downs are fine"],
  [4, "Growth", "Accept bigger swings for growth"],
  [5, "Adventurous", "Comfortable with large swings"],
];
const horizonChoices: Array<[number, string]> = [
  [2, "Less than 3 years"],
  [5, "3–7 years"],
  [10, "About 10 years"],
  [20, "20 years or more"],
];

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
      setStatus("Saved");
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

  if (!profile && !error) return <Loading className="page-loading" label="Loading your settings…" />;
  if (!profile) return <p className="error" role="alert">{error}</p>;

  const horizon = profile.time_horizon_years ?? 10;
  const horizonOptions = horizonChoices.some(([value]) => value === horizon)
    ? horizonChoices
    : [...horizonChoices, [horizon, `${horizon} years`] as [number, string]].sort((left, right) => left[0] - right[0]);

  return <>
    <header className="page-header"><div><p className="eyebrow">Settings</p><h1>Your investing profile</h1></div></header>
    {status && <p className="notice" role="status">{status}</p>}
    {error && <p className="error" role="alert">{error}</p>}
    <div className="profile-settings-grid">
      <form className="panel settings-form" onSubmit={saveProfile}>
        <h2>About your investing</h2>
        <p className="muted">Used to tailor insights and the assistant. You can change this anytime.</p>
        <fieldset className="risk-choices">
          <legend>How do you feel about ups and downs?</legend>
          {riskChoices.map(([value, label, hint]) => (
            <label key={value} className="risk-choice">
              <input type="radio" name="risk_tolerance" value={value} defaultChecked={(profile.risk_tolerance ?? 3) === value} />
              <span><strong>{label}</strong><small>{hint}</small></span>
            </label>
          ))}
        </fieldset>
        <label>When will you need this money?
          <select name="time_horizon_years" defaultValue={horizon}>
            {horizonOptions.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </label>
        <label>Your goals <span className="label-hint">optional</span><textarea name="goals" defaultValue={profile.goals ?? ""} placeholder="e.g. retirement, buying a home, long-term growth" rows={3}/></label>
        <button className="primary">Save</button>
      </form>
      <details className="panel data-controls-panel">
        <summary><h2>Your data &amp; account</h2><span className="muted">Download a copy or delete your account</span></summary>
        <section className="data-controls">
          <div><p className="muted">Download a copy of your account and portfolio.</p></div>
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
      </details>
    </div>
  </>;
}
