import { useEffect, useState } from "react";
import { ApiError } from "../../api/client";
import { adminDeleteUser, adminRevokeSessions, adminUpdateUser, adminUsers } from "../../api/endpoints";
import type { AdminUser } from "../../api/types";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { Icon } from "../../components/Icon";
import { Badge, Button, Card } from "../../components/ui";
import { useAuth } from "../../context/AuthContext";
import { useToast } from "../../context/ToastContext";
import { useLoad } from "../../hooks/useLoad";
import { formatDateTime, timeAgo } from "../../utils/format";
import { Loadable, Pager } from "./shared";

const PAGE = 25;

export function UsersTab() {
  const { user: me } = useAuth();
  const toast = useToast();
  const [input, setInput] = useState("");
  const [query, setQuery] = useState("");
  const [offset, setOffset] = useState(0);
  const [busy, setBusy] = useState("");
  const [toDelete, setToDelete] = useState<AdminUser | null>(null);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setQuery(input.trim());
      setOffset(0);
    }, 300);
    return () => window.clearTimeout(timer);
  }, [input]);

  const state = useLoad(() => adminUsers({ q: query, limit: PAGE, offset }), [query, offset]);

  const act = async (user: AdminUser, label: string, work: () => Promise<unknown>) => {
    setBusy(user.id);
    try {
      await work();
      toast.success(`${label}: ${user.email}`);
      await state.reload();
    } catch (caught) {
      toast.error(caught instanceof ApiError ? caught.message : "That did not work. Please try again.");
    } finally {
      setBusy("");
    }
  };

  return (
    <Card>
      <div className="toolbar">
        <label className="search-box">
          <Icon name="search" size={16} />
          <span className="sr-only">Search users</span>
          <input type="search" placeholder="Search by name or email" value={input} onChange={(e) => setInput(e.target.value)} maxLength={100} />
        </label>
        <Button variant="secondary" onClick={() => void state.reload()}>
          <Icon name="refresh" size={16} /> Refresh
        </Button>
      </div>

      <Loadable state={state}>
        {(data) => (
          <>
            {data.users.length === 0 ? (
              <p className="muted">No users match.</p>
            ) : (
              <div className="table-wrap">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>User</th>
                      <th>Status</th>
                      <th>Sign-in</th>
                      <th className="num">Trips</th>
                      <th>Last sign-in</th>
                      <th>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.users.map((user) => {
                      const self = user.email === me?.email;
                      const working = busy === user.id;
                      return (
                        <tr key={user.id}>
                          <td>
                            <strong>{user.name || user.email.split("@")[0]}</strong>
                            <span className="cell-sub">{user.email}</span>
                          </td>
                          <td>
                            <div className="badges">
                              {user.role === "admin" && <Badge tone="brand">Admin</Badge>}
                              {user.is_active ? <Badge tone="success">Active</Badge> : <Badge tone="danger">Disabled</Badge>}
                              {!user.email_verified && <Badge tone="warning">Unverified</Badge>}
                            </div>
                          </td>
                          <td>{[user.has_password && "Password", user.has_google && "Google"].filter(Boolean).join(" + ") || "-"}</td>
                          <td className="num">{user.trips}</td>
                          <td title={formatDateTime(user.last_login)}>{user.last_login ? timeAgo(user.last_login) : "Never"}</td>
                          <td>
                            {self ? (
                              <span className="muted small">You</span>
                            ) : (
                              <div className="row-actions">
                                {user.role === "admin" ? (
                                  <Button variant="ghost" disabled={working} onClick={() => void act(user, "Administrator removed", () => adminUpdateUser(user.id, { role: "user" }))}>
                                    Remove admin
                                  </Button>
                                ) : (
                                  <Button
                                    variant="ghost"
                                    disabled={working || !user.email_verified}
                                    title={user.email_verified ? undefined : "Verify the email first"}
                                    onClick={() => void act(user, "Made administrator", () => adminUpdateUser(user.id, { role: "admin" }))}
                                  >
                                    Make admin
                                  </Button>
                                )}
                                {!user.email_verified && (
                                  <Button variant="ghost" disabled={working} onClick={() => void act(user, "Email verified", () => adminUpdateUser(user.id, { verify_email: true }))}>
                                    Verify
                                  </Button>
                                )}
                                <Button
                                  variant="ghost"
                                  disabled={working}
                                  onClick={() => void act(user, user.is_active ? "Disabled" : "Enabled", () => adminUpdateUser(user.id, { is_active: !user.is_active }))}
                                >
                                  {user.is_active ? "Disable" : "Enable"}
                                </Button>
                                <Button variant="ghost" disabled={working} onClick={() => void act(user, "Signed out everywhere", () => adminRevokeSessions(user.id))}>
                                  Sign out
                                </Button>
                                <Button variant="ghost" disabled={working} onClick={() => setToDelete(user)} aria-label={`Delete ${user.email}`}>
                                  <Icon name="trash" size={16} />
                                </Button>
                              </div>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
            <Pager total={data.total} offset={offset} limit={PAGE} onChange={setOffset} />
          </>
        )}
      </Loadable>

      <ConfirmDialog
        open={toDelete !== null}
        title="Delete this user?"
        confirmLabel="Delete user"
        danger
        busy={busy !== ""}
        onCancel={() => setToDelete(null)}
        onConfirm={() => {
          const target = toDelete;
          setToDelete(null);
          if (target) void act(target, "User deleted", () => adminDeleteUser(target.id));
        }}
      >
        <p>
          This permanently deletes <strong>{toDelete?.email}</strong>, their sign-in methods and all of their trips ({toDelete?.trips ?? 0}). It cannot be undone.
        </p>
      </ConfirmDialog>
    </Card>
  );
}
