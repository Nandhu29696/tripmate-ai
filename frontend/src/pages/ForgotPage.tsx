import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { ApiError } from "../api/client";
import * as endpoints from "../api/endpoints";
import { Icon } from "../components/Icon";
import { Button, Field } from "../components/ui";
import { useToast } from "../context/ToastContext";

export function ForgotPage() {
  const toast = useToast();
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState("");

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!email.trim()) {
      toast.error("Please enter the email for your account.");
      return;
    }
    setBusy(true);
    try {
      const result = await endpoints.forgotPassword(email.trim());
      toast.info(result.message);
      setDone(result.message);
    } catch (caught) {
      toast.error(caught instanceof ApiError ? caught.message : "Something went wrong. Please try again.");
    } finally {
      setBusy(false);
    }
  };

  if (done) {
    return (
      <div className="auth-success">
        <span className="auth-success-icon">
          <Icon name="mail" size={26} />
        </span>
        <h2>Check your email</h2>
        <p className="muted">{done} The link works once and expires in one hour.</p>
        <Link to="/login" className="btn btn-secondary">
          Back to sign in
        </Link>
      </div>
    );
  }

  return (
    <>
      <header className="auth-head">
        <h2>Reset your password</h2>
        <p className="muted">Enter your email and we'll send you a link to choose a new one.</p>
      </header>
      <form onSubmit={(event) => void submit(event)} noValidate className="form-stack">
        <Field label="Email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" maxLength={254} required />
        <Button type="submit" block loading={busy}>
          Send reset link
        </Button>
        <p className="center small">
          <Link to="/login">Back to sign in</Link>
        </p>
      </form>
    </>
  );
}
