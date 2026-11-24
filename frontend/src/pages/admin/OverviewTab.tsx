import { adminOverview } from "../../api/endpoints";
import type { RequestStats, TripStatus } from "../../api/types";
import { Badge, Card } from "../../components/ui";
import { useLoad } from "../../hooks/useLoad";
import { formatMs, STATUS_LABEL } from "../../utils/format";
import { Loadable, StatCard } from "./shared";

const HOUR = 3_600_000;

/** One bar per hour for the whole window, including quiet hours (shown as a thin stub). */
function RequestChart({ stats }: { stats: RequestStats }) {
  const lastHour = Math.floor(Date.now() / HOUR) * HOUR;
  const byHour = new Map(stats.series.map((point) => [Math.floor(Date.parse(point.hour) / HOUR) * HOUR, point]));
  const slots = Array.from({ length: stats.hours }, (_, index) => {
    const time = lastHour - (stats.hours - 1 - index) * HOUR;
    const point = byHour.get(time);
    return { time, requests: point?.requests ?? 0, errors: point?.errors ?? 0 };
  });
  const max = Math.max(1, ...slots.map((slot) => slot.requests));
  const clock = (time: number) => new Date(time).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", hour12: false });

  return (
    <div>
      <div className="bar-chart" role="img" aria-label={`Requests per hour over the last ${stats.hours} hours; busiest hour ${max}`}>
        {slots.map((slot) => (
          <span key={slot.time} className="bar" title={`${clock(slot.time)}: ${slot.requests} request(s), ${slot.errors} server error(s)`}>
            <span className={`bar-fill${slot.requests === 0 ? " is-empty" : ""}`} style={{ height: `${slot.requests === 0 ? 2 : Math.max(6, (slot.requests / max) * 100)}%` }}>
              {slot.errors > 0 && <span className="bar-errors" style={{ height: `${Math.min(100, (slot.errors / slot.requests) * 100)}%` }} />}
            </span>
          </span>
        ))}
      </div>
      <div className="chart-axis" aria-hidden="true">
        <span>{clock(slots[0]?.time ?? lastHour)}</span>
        <span>peak {max} / hour</span>
        <span>now</span>
      </div>
    </div>
  );
}

export function OverviewTab() {
  const state = useLoad(adminOverview, [], 15000);
  return (
    <Loadable state={state}>
      {(data) => (
        <div className="stack">
          <div className="stat-grid">
            <StatCard icon="users" label="Users" value={data.users.total} sub={`${data.users.new_7d} new this week`} />
            <StatCard icon="plane" label="Trips" value={data.trips.total} sub={`${data.trips.last_24h} in the last 24 h`} />
            <StatCard
              icon="activity"
              label="Requests (24 h)"
              value={data.requests.total}
              sub={`${data.requests.client_errors} client / ${data.requests.server_errors} server errors`}
              tone={data.requests.server_errors ? "danger" : "success"}
            />
            <StatCard icon="clock" label="Response time" value={formatMs(data.requests.avg_ms)} sub={`95th percentile ${formatMs(data.requests.p95_ms)}`} />
            <StatCard
              icon="database"
              label="SQL (recent)"
              value={data.sql.count}
              sub={`${data.sql.slow} slow, ${data.sql.errors} failed, avg ${formatMs(data.sql.avg_ms)}`}
              tone={data.sql.slow || data.sql.errors ? "warning" : "success"}
            />
            <StatCard
              icon="shield"
              label="Service"
              value={data.ready.ready ? "Healthy" : "Degraded"}
              sub={`Database: ${data.ready.database}`}
              tone={data.ready.ready ? "success" : "danger"}
            />
          </div>

          <div className="two-col">
            <Card>
              <h2 className="card-title">Requests per hour</h2>
              <RequestChart stats={data.requests} />
            </Card>
            <Card>
              <h2 className="card-title">Trips by status</h2>
              {Object.keys(data.trips.by_status).length === 0 ? (
                <p className="muted small">No trips yet.</p>
              ) : (
                <ul className="kv-list">
                  {Object.entries(data.trips.by_status).map(([status, count]) => (
                    <li key={status}>
                      <span>{STATUS_LABEL[status as TripStatus] ?? status}</span>
                      <strong>{count}</strong>
                    </li>
                  ))}
                </ul>
              )}
              <h2 className="card-title spaced">Accounts</h2>
              <ul className="kv-list">
                <li>
                  <span>Verified email</span>
                  <strong>{data.users.verified}</strong>
                </li>
                <li>
                  <span>Signed up with Google</span>
                  <strong>{data.users.google}</strong>
                </li>
                <li>
                  <span>Administrators</span>
                  <strong>{data.users.admins}</strong>
                </li>
                <li>
                  <span>Disabled</span>
                  <strong>{data.users.disabled ? <Badge tone="warning">{data.users.disabled}</Badge> : 0}</strong>
                </li>
              </ul>
            </Card>
          </div>
        </div>
      )}
    </Loadable>
  );
}
