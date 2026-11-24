import type { ReactNode } from "react";
import { Icon, type IconName } from "../../components/Icon";
import { Button } from "../../components/ui";
import type { Loaded } from "../../hooks/useLoad";

export function StatCard({
  icon,
  label,
  value,
  sub,
  tone = "brand",
}: {
  icon: IconName;
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  tone?: "brand" | "success" | "warning" | "danger";
}) {
  return (
    <div className={`stat-card tone-${tone}`}>
      <span className="stat-icon">
        <Icon name={icon} size={20} />
      </span>
      <div>
        <span className="stat-label">{label}</span>
        <strong className="stat-value">{value}</strong>
        {sub && <span className="stat-sub">{sub}</span>}
      </div>
    </div>
  );
}

/** Shows the loading / error state of a request, or its content. */
export function Loadable<T>({ state, children }: { state: Loaded<T>; children: (data: T) => ReactNode }) {
  if (state.error && !state.data) {
    return (
      <div className="banner banner-error" role="alert">
        <Icon name="alert" size={18} /> {state.error}{" "}
        <Button variant="secondary" onClick={() => void state.reload()}>
          Try again
        </Button>
      </div>
    );
  }
  if (!state.data) {
    return (
      <p className="muted" role="status">
        Loading…
      </p>
    );
  }
  return <>{children(state.data)}</>;
}

export function Pager({ total, offset, limit, onChange }: { total: number; offset: number; limit: number; onChange: (offset: number) => void }) {
  if (total <= limit) return null;
  const from = offset + 1;
  const to = Math.min(total, offset + limit);
  return (
    <div className="pager">
      <span className="muted small">
        {from}-{to} of {total}
      </span>
      <Button variant="secondary" disabled={offset === 0} onClick={() => onChange(Math.max(0, offset - limit))}>
        Previous
      </Button>
      <Button variant="secondary" disabled={to >= total} onClick={() => onChange(offset + limit)}>
        Next
      </Button>
    </div>
  );
}

export function statusTone(status: number): "success" | "neutral" | "warning" | "danger" {
  if (status >= 500) return "danger";
  if (status >= 400) return "warning";
  if (status >= 300) return "neutral";
  return "success";
}
