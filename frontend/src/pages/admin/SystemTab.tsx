import { useState } from "react";
import { ApiError } from "../../api/client";
import { adminPurge, adminSystem } from "../../api/endpoints";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { Badge, Button, Card } from "../../components/ui";
import { useToast } from "../../context/ToastContext";
import { useLoad } from "../../hooks/useLoad";
import { Loadable } from "./shared";

const SETTING_LABEL: Record<string, string> = {
  model: "AI model",
  max_revisions: "Revisions allowed per trip",
  plans_per_user_per_hour: "Plans per user per hour",
  plans_per_day: "Plans per day (everyone)",
  session_hours: "Sign-in lasts (hours)",
  trip_retention_days: "Trips kept for (days)",
  log_retention_days: "Request logs kept for (days)",
  slow_query_ms: "Slow query threshold (ms)",
  sql_logging: "SQL logging",
  public_base_url: "Public address",
  admin_emails_configured: "Addresses in ADMIN_EMAILS",
};

const INTEGRATION_LABEL: Record<string, string> = {
  google_sign_in: "Google sign-in",
  email_delivery: "Email delivery (SMTP)",
  database_ssl: "Database uses TLS",
};

export function SystemTab() {
  const toast = useToast();
  const state = useLoad(adminSystem, []);
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);

  const purge = async () => {
    setBusy(true);
    try {
      const result = await adminPurge();
      toast.success(`Removed ${result.trips_removed} expired trip(s).`);
      setConfirm(false);
    } catch (caught) {
      toast.error(caught instanceof ApiError ? caught.message : "The clean-up failed.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Loadable state={state}>
      {(data) => (
        <div className="two-col">
          <Card>
            <h2 className="card-title">Service</h2>
            <ul className="kv-list">
              <li>
                <span>Version</span>
                <strong>{data.version}</strong>
              </li>
              <li>
                <span>Status</span>
                <Badge tone={data.ready.ready ? "success" : "danger"}>{data.ready.ready ? "Ready" : "Not ready"}</Badge>
              </li>
              <li>
                <span>Database</span>
                <strong>{data.ready.database}</strong>
              </li>
            </ul>
            <h2 className="card-title spaced">Integrations</h2>
            <ul className="kv-list">
              {Object.entries(data.integrations).map(([key, on]) => (
                <li key={key}>
                  <span>{INTEGRATION_LABEL[key] ?? key}</span>
                  {on === null ? <Badge>Unknown</Badge> : <Badge tone={on ? "success" : "neutral"}>{on ? "On" : "Off"}</Badge>}
                </li>
              ))}
            </ul>
            <h2 className="card-title spaced">Maintenance</h2>
            <p className="muted small">Trips and request logs older than their retention period are removed automatically every few hours. You can run the clean-up now.</p>
            <Button variant="secondary" onClick={() => setConfirm(true)}>
              Run clean-up now
            </Button>
          </Card>

          <Card>
            <h2 className="card-title">Settings</h2>
            <p className="muted small">Read-only. Change these in the server's environment file and restart. Secrets are never shown.</p>
            <ul className="kv-list">
              {Object.entries(data.settings).map(([key, value]) => (
                <li key={key}>
                  <span>{SETTING_LABEL[key] ?? key}</span>
                  <strong className="wrap">{typeof value === "boolean" ? (value ? "On" : "Off") : String(value)}</strong>
                </li>
              ))}
              <li>
                <span>Minimum password length</span>
                <strong>{data.password_policy.min_length}</strong>
              </li>
            </ul>
          </Card>

          <ConfirmDialog open={confirm} title="Run the clean-up now?" confirmLabel="Run clean-up" busy={busy} onCancel={() => setConfirm(false)} onConfirm={() => void purge()}>
            <p>Trips that have not been touched for the retention period will be deleted permanently.</p>
          </ConfirmDialog>
        </div>
      )}
    </Loadable>
  );
}
