import { Link, useRouter } from "../routing/Router";

export type PageTab = { to: string; label: string };

/** Secondary navigation between closely related pages (e.g. Holdings ↔ Activity). */
export function PageTabs({ tabs, label }: { tabs: PageTab[]; label: string }) {
  const { path } = useRouter();
  return (
    <nav className="page-tabs" aria-label={label}>
      {tabs.map((tab) => (
        <Link key={tab.to} to={tab.to} active={path === tab.to}>{tab.label}</Link>
      ))}
    </nav>
  );
}
