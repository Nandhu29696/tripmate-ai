import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError } from "../api/client";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { Icon } from "../components/Icon";
import { Badge, Card } from "../components/ui";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import { useTrips } from "../context/TripsContext";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { initials } from "../utils/format";

export function AccountPage() {
  useDocumentTitle("Account");
  const { user, removeAccount } = useAuth();
  const { trips } = useTrips();
  const toast = useToast();
  const navigate = useNavigate();
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);

  if (!user) return null;

  const deleteAccount = async () => {
    setBusy(true);
    try {
      await removeAccount();
      toast.success("Your account and all saved trips were deleted.");
      navigate("/login", { replace: true });
    } catch (caught) {
      toast.error(caught instanceof ApiError ? caught.message : "Could not delete your account. Please try again.");
      setBusy(false);
      setConfirming(false);
    }
  };

  return (
    <div className="page narrow">
      <header className="page-head">
        <div>
          <h1>Account</h1>
          <p className="muted">Your profile and how you sign in.</p>
        </div>
      </header>

      <Card>
        <div className="profile">
          <span className="avatar avatar-lg">{initials(user.name)}</span>
          <div>
            <h2 className="card-title">{user.name}</h2>
            <p className="muted">{user.email}</p>
          </div>
        </div>
        <dl className="detail-list">
          <div>
            <dt>Saved trips</dt>
            <dd>{trips.length}</dd>
          </div>
          <div>
            <dt>
              <Icon name="mail" size={16} /> Email and password
            </dt>
            <dd>{user.has_password ? <Badge tone="success">Set up</Badge> : <Badge>Not set</Badge>}</dd>
          </div>
          <div>
            <dt>
              <Icon name="shield" size={16} /> Google
            </dt>
            <dd>{user.has_google ? <Badge tone="success">Connected</Badge> : <Badge>Not connected</Badge>}</dd>
          </div>
        </dl>
        {!user.has_password && <p className="muted small">Signed in with Google only. You can add a password any time with "Forgot your password?" on the sign-in page.</p>}
      </Card>

      <Card className="danger-zone">
        <h2 className="card-title">Delete account</h2>
        <p className="muted">Permanently deletes your account, every saved trip and its plan. This can't be undone.</p>
        <button type="button" className="btn btn-danger" onClick={() => setConfirming(true)}>
          <Icon name="trash" size={16} /> Delete my account
        </button>
      </Card>

      <ConfirmDialog
        open={confirming}
        title="Delete your account?"
        confirmLabel="Delete account"
        requireText="DELETE"
        danger
        busy={busy}
        onConfirm={() => void deleteAccount()}
        onCancel={() => setConfirming(false)}
      >
        <p>
          This permanently deletes your account and {trips.length === 1 ? "your 1 saved trip" : `all ${trips.length} saved trips`}.
        </p>
      </ConfirmDialog>
    </div>
  );
}
