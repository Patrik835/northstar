import { useEffect, useState, type FormEvent } from "react";
import { api } from "../../api/client";
import type { User } from "../../api/types";
import { useAuth } from "../auth/AuthContext";

type Operations = {
  backup: { status: "ok" | "stale" | "missing"; last_success_at: string | null };
  jobs: Array<{
    id: string;
    job_name: string;
    status: string;
    safe_detail: string | null;
    started_at: string;
    duration_ms: number | null;
  }>;
  sync_failures: Array<{
    id: string;
    status: string;
    safe_detail: string | null;
    started_at: string;
  }>;
};

function time(value: string | null) {
  return value ? new Date(value).toLocaleString() : "Not available";
}

export function AdminPage() {
  const { user } = useAuth();
  const [users, setUsers] = useState<User[]>([]);
  const [operations, setOperations] = useState<Operations | null>(null);
  const [message, setMessage] = useState("");

  async function refresh() {
    const [userRows, operationRows] = await Promise.all([
      api<User[]>("/admin/users"),
      api<Operations>("/admin/operations"),
    ]);
    setUsers(userRows);
    setOperations(operationRows);
  }

  useEffect(() => {
    if (user?.is_admin) void refresh();
  }, [user]);

  if (!user?.is_admin) return <p className="error" role="alert">Admin access required.</p>;

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      await api("/admin/users", {
        method: "POST",
        body: JSON.stringify({
          username: form.get("username"),
          email: form.get("email") || null,
          initial_password: form.get("password"),
          is_admin: false,
        }),
      });
      event.currentTarget.reset();
      setMessage("User created.");
      await refresh();
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "Could not create user");
    }
  }

  return <>
    <header className="page-header"><div><p className="eyebrow">Administration</p><h1>Users & operations</h1></div></header>
    <div className="admin-grid">
      <form className="panel settings-form" onSubmit={submit}>
        <h2>Create account</h2>
        <label>Username<input name="username" required minLength={3}/></label>
        <label>Email <span className="label-hint">optional</span><input name="email" type="email"/></label>
        <label>Initial password<input name="password" type="password" minLength={12} required/></label>
        <button className="primary">Create user</button>
        {message && <p className="notice" role="status">{message}</p>}
      </form>
      <section className="panel">
        <h2>Existing users</h2>
        <div className="user-list">{users.map((item) => <div key={item.id}><span>{item.username}</span><small>{item.is_admin ? "Admin" : "Member"}</small></div>)}</div>
      </section>
      <section className="panel operations-panel">
        <div className="panel-heading"><div><p className="eyebrow">System</p><h2>Operations</h2></div><span className={`status ${operations?.backup.status ?? "missing"}`}>Backup {operations?.backup.status ?? "unknown"}</span></div>
        <p className="muted">Last verified backup: {time(operations?.backup.last_success_at ?? null)}</p>
        <h3>Recent scheduled jobs</h3>
        <div className="operation-list">
          {(operations?.jobs ?? []).slice(0, 8).map((job) => <div key={job.id}><span><strong>{job.job_name}</strong><small>{time(job.started_at)}{job.duration_ms !== null ? ` · ${job.duration_ms} ms` : ""}</small></span><em className={job.status}>{job.status}</em></div>)}
          {operations?.jobs.length === 0 && <p className="muted">No scheduled job runs yet.</p>}
        </div>
        {Boolean(operations?.sync_failures.length) && <details><summary>Recent connector warnings and failures</summary><div className="operation-list">{operations?.sync_failures.slice(0, 8).map((run) => <div key={run.id}><span><strong>{run.status}</strong><small>{run.safe_detail ?? "No safe detail available"}</small></span><time>{time(run.started_at)}</time></div>)}</div></details>}
      </section>
    </div>
  </>;
}
