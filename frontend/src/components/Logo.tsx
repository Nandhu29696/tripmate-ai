import { Link } from "react-router-dom";
import { Icon } from "./Icon";

export function Logo({ to = "/", light = false }: { to?: string; light?: boolean }) {
  return (
    <Link to={to} className={`logo${light ? " logo-light" : ""}`} aria-label="TripMate AI home">
      <span className="logo-mark">
        <Icon name="plane" size={18} />
      </span>
      <span className="logo-text">
        TripMate <span>AI</span>
      </span>
    </Link>
  );
}
