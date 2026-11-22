import type { ReactNode } from "react";
import { useFeatures } from "../api/features";
import { FreshnessStatus } from "../components/FreshnessStatus";
import { PageTabs, type PageTab } from "../components/PageTabs";
import { ThemeToggle } from "../components/ThemeToggle";
import { useAuth } from "../features/auth/AuthContext";
import { Link, useRouter } from "../routing/Router";

// Closely related pages share one sidebar entry and switch with tabs at the top.
const sections: Array<{ to: string; label: string; tabs?: PageTab[] }> = [
  { to: "/", label: "Overview" },
  {
    to: "/holdings",
    label: "Holdings",
    tabs: [
      { to: "/holdings", label: "Positions" },
      { to: "/activity", label: "Activity" },
    ],
  },
  {
    to: "/analytics",
    label: "Insights",
    tabs: [
      { to: "/analytics", label: "Analytics" },
      { to: "/updates", label: "News & alerts" },
    ],
  },
  { to: "/connections", label: "Sources" },
];

export function AppLayout({ children }: { children: ReactNode }) {
  const { user, logout } = useAuth();
  const { path } = useRouter();
  const features = useFeatures();
  const current = sections.find((section) =>
    section.tabs ? section.tabs.some((tab) => tab.to === path) : section.to === path,
  );
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">Skip to main content</a>
      <aside className="sidebar" aria-label="Application sidebar">
        <div className="brand"><span>Northstar</span><small>Investment OS</small></div>
        <nav aria-label="Primary navigation">
          {sections.map((section) => (
            <Link key={section.to} to={section.to} active={current === section}>{section.label}</Link>
          ))}
          {features?.ai && <Link to="/assistant" active={path === "/assistant"}>AI assistant</Link>}
          <Link to="/profile" active={path === "/profile"}>Settings</Link>
          {user?.is_admin && <Link to="/admin" active={path === "/admin"}>Admin</Link>}
        </nav>
        <FreshnessStatus />
        <div className="user-block">
          <span>{user?.username}</span>
          <ThemeToggle />
          <button className="text-button" onClick={() => void logout()}>Sign out</button>
        </div>
      </aside>
      <main className="content" id="main-content" tabIndex={-1}>
        {current?.tabs && <PageTabs tabs={current.tabs} label={`${current.label} sections`} />}
        {children}
      </main>
    </div>
  );
}
