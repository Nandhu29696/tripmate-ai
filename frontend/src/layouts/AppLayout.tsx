import { useEffect, useState } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { Icon } from "../components/Icon";
import { Logo } from "../components/Logo";
import { Badge, Skeleton } from "../components/ui";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import { useTrips } from "../context/TripsContext";
import { useTheme } from "../hooks/useTheme";
import { initials, STATUS_LABEL, timeAgo } from "../utils/format";
import type { TripStatus } from "../api/types";

const TONE: Record<TripStatus, "brand" | "success" | "warning" | "danger" | "neutral"> = {
  awaiting_approval: "warning",
  completed: "success",
  blocked: "neutral",
  failed: "danger",
  running: "brand",
};

export function AppLayout() {
  const { user, signOut } = useAuth();
  const { trips, loading } = useTrips();
  const { theme, toggle } = useTheme();
  const toast = useToast();
  const navigate = useNavigate();
  const location = useLocation();
  const [open, setOpen] = useState(false);

  // Close the mobile drawer whenever the page changes.
  useEffect(() => setOpen(false), [location.pathname]);

  const name = user?.name ?? "Traveler";

  const handleSignOut = async () => {
    await signOut();
    toast.info("You have been signed out.");
    navigate("/login", { replace: true });
  };

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main">
        Skip to content
      </a>

      <header className="mobile-bar">
        <button type="button" className="icon-btn" aria-label="Open menu" aria-expanded={open} onClick={() => setOpen(true)}>
          <Icon name="menu" />
        </button>
        <Logo />
        <Link to="/account" className="avatar avatar-sm" aria-label="Your account">
          {initials(name)}
        </Link>
      </header>

      {open && <div className="scrim" onClick={() => setOpen(false)} aria-hidden="true" />}

      <aside className={`sidebar${open ? " is-open" : ""}`} aria-label="Sidebar">
        <div className="sidebar-head">
          <Logo />
          <button type="button" className="icon-btn sidebar-close" aria-label="Close menu" onClick={() => setOpen(false)}>
            <Icon name="x" />
          </button>
        </div>

        <Link to="/" className="btn btn-primary btn-block new-trip">
          <Icon name="plus" size={18} /> New trip
        </Link>

        <nav className="trip-nav" aria-label="Your trips">
          <h2 className="nav-heading">Your trips</h2>
          {loading && trips.length === 0 && <Skeleton lines={3} />}
          {!loading && trips.length === 0 && <p className="muted small nav-empty">Trips you plan will appear here.</p>}
          <ul>
            {trips.map((trip) => (
              <li key={trip.thread_id}>
                <NavLink to={`/trips/${trip.thread_id}`} className={({ isActive }) => `trip-link${isActive ? " is-active" : ""}`}>
                  <span className="trip-link-title">{trip.title || "Untitled trip"}</span>
                  <span className="trip-link-meta">
                    <Badge tone={TONE[trip.status]}>{STATUS_LABEL[trip.status]}</Badge>
                    <span>{timeAgo(trip.updated_at)}</span>
                  </span>
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>

        <div className="sidebar-foot">
          <Link to="/account" className="user-chip">
            <span className="avatar">{initials(name)}</span>
            <span className="user-chip-text">
              <strong>{name}</strong>
              <span>{user?.email}</span>
            </span>
          </Link>
          <div className="sidebar-actions">
            <button type="button" className="btn btn-ghost" onClick={toggle} aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}>
              <Icon name={theme === "dark" ? "sun" : "moon"} size={18} />
              {theme === "dark" ? "Light" : "Dark"}
            </button>
            <button type="button" className="btn btn-ghost" onClick={() => void handleSignOut()}>
              <Icon name="logout" size={18} /> Sign out
            </button>
          </div>
        </div>
      </aside>

      <main className="app-main" id="main">
        <Outlet />
      </main>
    </div>
  );
}
