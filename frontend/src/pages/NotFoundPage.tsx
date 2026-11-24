import { Link } from "react-router-dom";
import { Icon } from "../components/Icon";
import { Logo } from "../components/Logo";
import { useDocumentTitle } from "../hooks/useDocumentTitle";

export function NotFoundPage() {
  useDocumentTitle("Page not found");
  return (
    <div className="fullscreen-center column">
      <Logo />
      <Icon name="compass" size={44} />
      <h1>We took a wrong turn</h1>
      <p className="muted">That page doesn't exist.</p>
      <Link to="/" className="btn btn-primary">
        Back to TripMate
      </Link>
    </div>
  );
}
