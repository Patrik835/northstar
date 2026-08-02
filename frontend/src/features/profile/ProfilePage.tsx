import { useEffect, useState, type FormEvent } from "react";
import { api } from "../../api/client";

type Profile = { goals: string | null; risk_tolerance: number | null; time_horizon_years: number | null };

export function ProfilePage() {
  const [profile, setProfile] = useState<Profile | null>(null);
  const [saved, setSaved] = useState(false);
  useEffect(() => { api<Profile>("/profile").then(setProfile); }, []);
  async function submit(event: FormEvent<HTMLFormElement>) { event.preventDefault(); const form = new FormData(event.currentTarget); const result = await api<Profile>("/profile", { method: "PUT", body: JSON.stringify({ goals: form.get("goals") || null, risk_tolerance: Number(form.get("risk_tolerance")), time_horizon_years: Number(form.get("time_horizon_years")) }) }); setProfile(result); setSaved(true); }
  if (!profile) return <p>Loading profile…</p>;
  return <><header className="page-header"><div><p className="eyebrow">Personal context</p><h1>Goals & risk</h1></div></header><form className="panel settings-form" onSubmit={submit}><label>Investment goals<textarea name="goals" defaultValue={profile.goals ?? ""} placeholder="Retirement, long-term wealth growth…" rows={5}/></label><label>Risk tolerance <span className="label-hint">1 cautious · 5 aggressive</span><input name="risk_tolerance" type="range" min="1" max="5" defaultValue={profile.risk_tolerance ?? 3}/></label><label>Time horizon (years)<input name="time_horizon_years" type="number" min="1" max="100" defaultValue={profile.time_horizon_years ?? 10}/></label><button className="primary">Save profile</button>{saved && <span className="success">Saved</span>}</form></>;
}

