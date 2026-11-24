import { NavLink, Outlet } from "react-router-dom";
import { Icon, type IconName } from "../../components/Icon";
import { useDocumentTitle } from "../../hooks/useDocumentTitle";

const TABS: { to: string; label: string; icon: IconName; end?: boolean }[] = [
  { to: "/admin", label: "Overview", icon: "activity", end: true },
  { to: "/admin/users", label: "Users", icon: "users" },
  { to: "/admin/trips", label: "Trips", icon: "plane" },
  { to: "/admin/logs", label: "Logs", icon: "database" },
  { to: "/admin/system", label: "System", icon: "settings" },
];

export function AdminLayout() {
  useDocumentTitle("Admin");
  return (
    <div className="page wide">
      <header className="page-head">
        <div className="page-head-main">
          <span className="eyebrow">Administration</span>
          <h1>Admin console</h1>
          <p className="muted">Manage accounts and trips, and watch requests, database queries and admin actions.</p>
        </div>
      </header>
      <nav className="tabs admin-tabs" aria-label="Admin sections">
        {TABS.map((tab) => (
          <NavLink key={tab.to} to={tab.to} end={tab.end} className={({ isActive }) => `tab${isActive ? " is-active" : ""}`}>
            <Icon name={tab.icon} size={16} /> {tab.label}
          </NavLink>
        ))}
      </nav>
      <Outlet />
    </div>
  );
}
