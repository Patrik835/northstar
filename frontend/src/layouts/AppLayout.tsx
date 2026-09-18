import type { ReactNode } from "react";
import { useAuth } from "../features/auth/AuthContext";
import { Link, useRouter } from "../routing/Router";

export function AppLayout({ children }: { children: ReactNode }) {
  const { user, logout } = useAuth();
  const { path } = useRouter();
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">Skip to main content</a>
      <aside className="sidebar" aria-label="Application sidebar">
        <div className="brand"><span>Northstar</span><small>Investment OS</small></div>
        <nav aria-label="Primary navigation">
          <Link to="/" active={path === "/"}>Overview</Link>
          <Link to="/holdings" active={path === "/holdings"}>Holdings</Link>
          <Link to="/activity" active={path === "/activity"}>Activity</Link>
          <Link to="/analytics" active={path === "/analytics"}>Analytics</Link>
          <Link to="/connections" active={path === "/connections"}>Connections</Link>
          <Link to="/updates" active={path === "/updates"}>Updates</Link>
          <Link to="/assistant" active={path === "/assistant"}>AI assistant</Link>
          <Link to="/profile" active={path === "/profile"}>Settings</Link>
          {user?.is_admin && <Link to="/admin" active={path === "/admin"}>Admin</Link>}
        </nav>
        <div className="user-block"><span>{user?.username}</span><button className="text-button" onClick={() => void logout()}>Sign out</button></div>
      </aside>
      <main className="content" id="main-content" tabIndex={-1}>{children}</main>
    </div>
  );
}
