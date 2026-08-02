import type { ReactNode } from "react";
import { useAuth } from "../features/auth/AuthContext";
import { Link, useRouter } from "../routing/Router";

export function AppLayout({ children }: { children: ReactNode }) {
  const { user, logout } = useAuth();
  const { path } = useRouter();
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand"><span>Northstar</span><small>Investment OS</small></div>
        <nav>
          <Link to="/" active={path === "/"}>Overview</Link>
          <Link to="/connections" active={path === "/connections"}>Connections</Link>
          <Link to="/assistant" active={path === "/assistant"}>AI assistant</Link>
          <Link to="/profile" active={path === "/profile"}>Goals & risk</Link>
          {user?.is_admin && <Link to="/admin" active={path === "/admin"}>Admin</Link>}
        </nav>
        <div className="user-block"><span>{user?.username}</span><button className="text-button" onClick={() => void logout()}>Sign out</button></div>
      </aside>
      <main className="content">{children}</main>
    </div>
  );
}
