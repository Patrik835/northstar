import { useEffect, useState, type FormEvent } from "react";
import { api } from "../../api/client";
import type { User } from "../../api/types";
import { useAuth } from "../auth/AuthContext";

export function AdminPage() {
  const { user } = useAuth(); const [users, setUsers] = useState<User[]>([]); const [message, setMessage] = useState("");
  async function refresh() { setUsers(await api<User[]>("/admin/users")); }
  useEffect(() => { if (user?.is_admin) void refresh(); }, [user]);
  if (!user?.is_admin) return <p className="error">Admin access required.</p>;
  async function submit(event: FormEvent<HTMLFormElement>) { event.preventDefault(); const form = new FormData(event.currentTarget); try { await api("/admin/users", { method: "POST", body: JSON.stringify({ username: form.get("username"), email: form.get("email") || null, initial_password: form.get("password"), is_admin: false }) }); event.currentTarget.reset(); setMessage("User created."); await refresh(); } catch (e) { setMessage(e instanceof Error ? e.message : "Could not create user"); } }
  return <><header className="page-header"><div><p className="eyebrow">Administration</p><h1>Users</h1></div></header><div className="admin-grid"><form className="panel settings-form" onSubmit={submit}><h2>Create account</h2><label>Username<input name="username" required minLength={3}/></label><label>Email <span className="label-hint">optional</span><input name="email" type="email"/></label><label>Initial password<input name="password" type="password" minLength={12} required/></label><button className="primary">Create user</button>{message && <p className="notice">{message}</p>}</form><section className="panel"><h2>Existing users</h2><div className="user-list">{users.map((item) => <div key={item.id}><span>{item.username}</span><small>{item.is_admin ? "Admin" : "Member"}</small></div>)}</div></section></div></>;
}

