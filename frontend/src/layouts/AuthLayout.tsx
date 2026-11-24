import { Outlet } from "react-router-dom";
import { Icon, type IconName } from "../components/Icon";
import { Logo } from "../components/Logo";

const POINTS: { icon: IconName; title: string; text: string }[] = [
  { icon: "users", title: "A team of travel agents", text: "Flights, hotels, weather and budget are researched in parallel, then combined into one plan." },
  { icon: "check", title: "You stay in control", text: "Review the draft, ask for changes, and approve only when it feels right." },
  { icon: "shield", title: "Private to you", text: "Your trips are saved to your account, and you can delete them any time." },
];

export function AuthLayout() {
  return (
    <div className="auth-shell">
      <aside className="auth-brand">
        <Logo light />
        <div className="auth-brand-body">
          <h1>Plan trips that feel like yours.</h1>
          <p>Tell us where you want to go. We do the research; you make the call.</p>
          <ul className="auth-points">
            {POINTS.map((point) => (
              <li key={point.title}>
                <span className="auth-point-icon">
                  <Icon name={point.icon} size={18} />
                </span>
                <div>
                  <strong>{point.title}</strong>
                  <span>{point.text}</span>
                </div>
              </li>
            ))}
          </ul>
        </div>
        <p className="auth-brand-foot">Built with FastAPI, LangGraph and MCP</p>
      </aside>

      <main className="auth-main" id="main">
        <div className="auth-mobile-logo">
          <Logo />
        </div>
        <div className="auth-card">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
