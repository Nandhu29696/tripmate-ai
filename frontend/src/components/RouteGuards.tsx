import { useEffect } from "react";
import { Navigate, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import { returnPath } from "../utils/format";
import { takeFlash } from "../utils/urlParams";
import { Button, Spinner } from "./ui";

function FullScreenSpinner() {
  return (
    <div className="fullscreen-center">
      <Spinner size={32} />
    </div>
  );
}

/** Pages that need a signed-in user. Remembers where the visitor was heading. */
export function RequireAuth() {
  const { status, refresh } = useAuth();
  const location = useLocation();

  if (status === "loading") return <FullScreenSpinner />;

  if (status === "error") {
    return (
      <div className="fullscreen-center column">
        <h1>We can't reach TripMate right now</h1>
        <p className="muted">Check your connection and try again.</p>
        <Button onClick={() => void refresh()}>Try again</Button>
      </div>
    );
  }

  if (status === "anonymous") {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }

  return <Outlet />;
}

/** Sign-in pages: signed-in visitors go straight to the app. */
export function RedirectIfAuthed() {
  const { status } = useAuth();
  const location = useLocation();
  if (status === "loading") return <FullScreenSpinner />;
  // Sends the visitor back to the page they originally asked for (set by RequireAuth).
  if (status === "authenticated") return <Navigate to={returnPath(location.state)} replace />;
  return <Outlet />;
}

/** Shows the message left by an email or Google redirect (see utils/urlParams). */
export function FlashMessages() {
  const toast = useToast();

  useEffect(() => {
    const flash = takeFlash();
    if (!flash) return;
    if (flash.kind === "success") toast.success(flash.message);
    else toast.error(flash.message);
  }, [toast]);

  return null;
}
