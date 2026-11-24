import { useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { ApiError } from "../api/client";
import * as endpoints from "../api/endpoints";
import { Icon } from "../components/Icon";
import { Button, PasswordField } from "../components/ui";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";

export function ResetPage() {
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const { refresh } = useAuth();
  const toast = useToast();
  const navigate = useNavigate();

  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  if (!token) {
    return (
      <div className="auth-success">
        <span className="auth-success-icon is-warning">
          <Icon name="alert" size={26} />
        </span>
        <h2>This link isn't valid</h2>
        <p className="muted">The reset link is missing or incomplete. Please request a new one.</p>
        <Link to="/forgot" className="btn btn-primary">
          Request a new link
        </Link>
      </div>
    );
  }

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError("");
    if (!password) {
      const message = "Please choose a new password.";
      setError(message);
      toast.error(message);
      return;
    }
    setBusy(true);
    try {
      await endpoints.resetPassword(token, password);
      await refresh(); // the server signed us in with the new password
      toast.success("Your password was changed. You are signed in.");
      navigate("/", { replace: true });
    } catch (caught) {
      const message = caught instanceof ApiError ? caught.message : "Something went wrong. Please try again.";
      setError(message);
      toast.error(message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <header className="auth-head">
        <h2>Choose a new password</h2>
        <p className="muted">Pick something you haven't used elsewhere. You'll be signed out of your other devices.</p>
      </header>
      <form onSubmit={(event) => void submit(event)} noValidate className="form-stack">
        {error && (
          <div className="banner banner-error" role="alert">
            <Icon name="alert" size={18} /> {error}{" "}
            {error.includes("expired") && <Link to="/forgot">Request a new link</Link>}
          </div>
        )}
        <PasswordField label="New password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" maxLength={128} required showStrength hint="Use at least 10 characters." />
        <Button type="submit" block loading={busy}>
          Set new password
        </Button>
      </form>
    </>
  );
}
