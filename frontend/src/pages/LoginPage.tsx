import { useState, type FormEvent } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { ApiError } from "../api/client";
import { Icon } from "../components/Icon";
import { Button, Field, PasswordField } from "../components/ui";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import { returnPath } from "../utils/format";

type Mode = "signin" | "signup";

function GoogleLogo() {
  return (
    <svg width="18" height="18" viewBox="0 0 48 48" aria-hidden="true" focusable="false">
      <path fill="#EA4335" d="M24 9.5c3.5 0 6.6 1.2 9.1 3.5l6.8-6.8C35.8 2.4 30.3 0 24 0 14.6 0 6.5 5.4 2.6 13.2l7.9 6.1C12.4 13.6 17.7 9.5 24 9.5z" />
      <path fill="#4285F4" d="M46.5 24.5c0-1.6-.1-3.1-.4-4.5H24v9h12.7c-.6 3-2.3 5.5-4.8 7.2l7.6 5.9c4.4-4.1 7-10.1 7-17.6z" />
      <path fill="#FBBC05" d="M10.5 28.7c-.5-1.5-.8-3-.8-4.7s.3-3.2.8-4.7l-7.9-6.1C.9 16.4 0 20.1 0 24s.9 7.6 2.6 10.8l7.9-6.1z" />
      <path fill="#34A853" d="M24 48c6.5 0 11.9-2.1 15.9-5.8l-7.6-5.9c-2.1 1.4-4.9 2.3-8.3 2.3-6.3 0-11.6-4.1-13.5-9.8l-7.9 6.1C6.5 42.6 14.6 48 24 48z" />
    </svg>
  );
}

export function LoginPage() {
  const { signIn, signUp, providers } = useAuth();
  const toast = useToast();
  const navigate = useNavigate();
  const location = useLocation();
  const [params, setParams] = useSearchParams();
  const mode: Mode = params.get("mode") === "signup" ? "signup" : "signin";

  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [sentTo, setSentTo] = useState("");

  const from = returnPath(location.state);

  const switchMode = (next: Mode) => {
    setParams(next === "signup" ? { mode: "signup" } : {}, { replace: true });
    setSentTo("");
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();

    if (!email.trim() || !password) {
      toast.error("Please enter your email and password.");
      return;
    }

    setBusy(true);
    try {
      if (mode === "signup") {
        await signUp(email.trim(), password, name.trim());
        toast.success(`Confirmation email sent to ${email.trim()}.`);
        setSentTo(email.trim());
        setPassword("");
      } else {
        await signIn(email.trim(), password);
        toast.success("You signed in successfully.");
        navigate(from, { replace: true });
      }
    } catch (caught) {
      if (caught instanceof ApiError && caught.code === "email_not_verified") {
        toast.info(caught.message);
      } else {
        toast.error(caught instanceof ApiError ? caught.message : "Something went wrong. Please try again.");
      }
    } finally {
      setBusy(false);
    }
  };

  if (sentTo) {
    return (
      <div className="auth-success">
        <span className="auth-success-icon">
          <Icon name="mail" size={26} />
        </span>
        <h2>Check your email</h2>
        <p className="muted">
          We sent a confirmation link to <strong>{sentTo}</strong>. Open it to finish creating your account. The link works once and expires in 24 hours.
        </p>
        <Button variant="secondary" onClick={() => switchMode("signin")}>
          Back to sign in
        </Button>
      </div>
    );
  }

  return (
    <>
      <header className="auth-head">
        <h2>{mode === "signup" ? "Create your account" : "Welcome back"}</h2>
        <p className="muted">{mode === "signup" ? "Save your trips and pick them up on any device." : "Sign in to plan your next trip."}</p>
      </header>

      <div className="tabs" role="tablist" aria-label="Sign in or create an account">
        <button type="button" role="tab" aria-selected={mode === "signin"} className={mode === "signin" ? "is-active" : ""} onClick={() => switchMode("signin")}>
          Sign in
        </button>
        <button type="button" role="tab" aria-selected={mode === "signup"} className={mode === "signup" ? "is-active" : ""} onClick={() => switchMode("signup")}>
          Create account
        </button>
      </div>

      {providers.google && (
        <>
          <a className="btn btn-google btn-block" href="/auth/google/login">
            <GoogleLogo /> Continue with Google
          </a>
          <div className="divider">
            <span>or use your email</span>
          </div>
        </>
      )}

      <form onSubmit={(event) => void submit(event)} noValidate className="form-stack">
        {mode === "signup" && <Field label="Your name (optional)" value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" maxLength={80} />}
        <Field label="Email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" maxLength={254} required />
        <PasswordField
          label="Password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoComplete={mode === "signup" ? "new-password" : "current-password"}
          maxLength={128}
          required
          showStrength={mode === "signup"}
          hint={mode === "signup" ? "Use at least 10 characters. A few random words make a strong password." : undefined}
        />

        <Button type="submit" block loading={busy}>
          {mode === "signup" ? "Create account" : "Sign in"}
        </Button>

        {mode === "signin" && (
          <p className="center small">
            <Link to="/forgot">Forgot your password?</Link>
          </p>
        )}
      </form>
    </>
  );
}
