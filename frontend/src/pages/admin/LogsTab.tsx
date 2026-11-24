import { useEffect, useState } from "react";
import { adminAuditLogs, adminRequestLogs, adminSqlLogs } from "../../api/endpoints";
import { Icon } from "../../components/Icon";
import { Badge, Button, Card } from "../../components/ui";
import { useLoad } from "../../hooks/useLoad";
import { formatDateTime, formatMs, formatTokens } from "../../utils/format";
import { Loadable, Pager, statusTone } from "./shared";

type View = "requests" | "sql" | "audit";
const VIEWS: { id: View; label: string }[] = [
  { id: "requests", label: "API requests" },
  { id: "sql", label: "SQL queries" },
  { id: "audit", label: "Admin actions" },
];
const PAGE = 50;

function useDebounced(value: string, ms = 300): string {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), ms);
    return () => window.clearTimeout(timer);
  }, [value, ms]);
  return debounced;
}

function RequestsView() {
  const [status, setStatus] = useState("");
  const [method, setMethod] = useState("");
  const [pathInput, setPathInput] = useState("");
  const [slow, setSlow] = useState(false);
  const [live, setLive] = useState(false);
  const [offset, setOffset] = useState(0);
  const path = useDebounced(pathInput.trim());
  const state = useLoad(
    () => adminRequestLogs({ status, method, path, min_ms: slow ? 500 : undefined, limit: PAGE, offset }),
    [status, method, path, slow, offset],
    live ? 5000 : 0,
  );

  return (
    <>
      <div className="toolbar">
        <label className="select-box">
          <span className="sr-only">Status</span>
          <select value={status} onChange={(e) => { setStatus(e.target.value); setOffset(0); }}>
            <option value="">Any status</option>
            <option value="2xx">2xx success</option>
            <option value="3xx">3xx redirect</option>
            <option value="4xx">4xx client error</option>
            <option value="5xx">5xx server error</option>
          </select>
        </label>
        <label className="select-box">
          <span className="sr-only">Method</span>
          <select value={method} onChange={(e) => { setMethod(e.target.value); setOffset(0); }}>
            <option value="">Any method</option>
            {["GET", "POST", "PATCH", "DELETE"].map((m) => (
              <option key={m}>{m}</option>
            ))}
          </select>
        </label>
        <label className="search-box">
          <Icon name="search" size={16} />
          <span className="sr-only">Path contains</span>
          <input type="search" placeholder="Path contains…" value={pathInput} onChange={(e) => { setPathInput(e.target.value); setOffset(0); }} maxLength={100} />
        </label>
        <label className="check">
          <input type="checkbox" checked={slow} onChange={(e) => { setSlow(e.target.checked); setOffset(0); }} /> Slow only (500 ms+)
        </label>
        <label className="check">
          <input type="checkbox" checked={live} onChange={(e) => setLive(e.target.checked)} /> Live (5 s)
        </label>
        <Button variant="secondary" onClick={() => void state.reload()}>
          <Icon name="refresh" size={16} /> Refresh
        </Button>
      </div>
      <Loadable state={state}>
        {(data) =>
          data.logs.length === 0 ? (
            <p className="muted">No requests match.</p>
          ) : (
            <>
              <div className="table-wrap">
                <table className="data-table log-table">
                  <thead>
                    <tr>
                      <th>Time</th>
                      <th>Method</th>
                      <th>Path</th>
                      <th>Status</th>
                      <th className="num">Duration</th>
                      <th className="num">AI tokens</th>
                      <th>User</th>
                      <th>IP</th>
                      <th>Request ID</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.logs.map((row) => (
                      <tr key={row.id}>
                        <td>{formatDateTime(row.ts)}</td>
                        <td>
                          <code>{row.method}</code>
                        </td>
                        <td className="wrap">
                          <code>{row.path}</code>
                        </td>
                        <td>
                          <Badge tone={statusTone(row.status)}>{row.status}</Badge>
                        </td>
                        <td className={`num${row.duration_ms >= 500 ? " is-slow" : ""}`}>{formatMs(row.duration_ms)}</td>
                        <td className="num" title={row.llm_calls ? `${row.input_tokens.toLocaleString()} in / ${row.output_tokens.toLocaleString()} out, ${row.llm_calls} AI calls` : undefined}>
                          {row.llm_calls ? (
                            <>
                              {formatTokens(row.input_tokens + row.output_tokens)}
                              <span className="cell-sub">{formatTokens(row.input_tokens)} in / {formatTokens(row.output_tokens)} out</span>
                            </>
                          ) : (
                            "-"
                          )}
                        </td>
                        <td>{row.user_id ? <code title={row.user_id}>{row.user_id.slice(0, 12)}…</code> : "-"}</td>
                        <td>{row.ip}</td>
                        <td>
                          <code>{row.request_id}</code>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <Pager total={data.logs.length === PAGE ? offset + PAGE + 1 : offset + data.logs.length} offset={offset} limit={PAGE} onChange={setOffset} />
            </>
          )
        }
      </Loadable>
    </>
  );
}

function SqlView() {
  const [input, setInput] = useState("");
  const [slow, setSlow] = useState(false);
  const [errors, setErrors] = useState(false);
  const [live, setLive] = useState(false);
  const q = useDebounced(input.trim());
  const state = useLoad(() => adminSqlLogs({ q, slow, errors, limit: 100 }), [q, slow, errors], live ? 5000 : 0);

  return (
    <>
      <p className="muted small">
        Statement text and timing only: values (passwords, tokens, trip text) are never recorded. The most recent statements are kept in memory and are cleared on restart.
      </p>
      <div className="toolbar">
        <label className="search-box">
          <Icon name="search" size={16} />
          <span className="sr-only">SQL contains</span>
          <input type="search" placeholder="SQL contains… (e.g. users)" value={input} onChange={(e) => setInput(e.target.value)} maxLength={100} />
        </label>
        <label className="check">
          <input type="checkbox" checked={slow} onChange={(e) => setSlow(e.target.checked)} /> Slow only
        </label>
        <label className="check">
          <input type="checkbox" checked={errors} onChange={(e) => setErrors(e.target.checked)} /> Failed only
        </label>
        <label className="check">
          <input type="checkbox" checked={live} onChange={(e) => setLive(e.target.checked)} /> Live (5 s)
        </label>
        <Button variant="secondary" onClick={() => void state.reload()}>
          <Icon name="refresh" size={16} /> Refresh
        </Button>
      </div>
      <Loadable state={state}>
        {(data) => (
          <>
            {!data.enabled && <div className="banner banner-info">SQL logging is switched off (LOG_SQL=false).</div>}
            <div className="chips">
              <span className="chip static">{data.summary.count} recorded</span>
              <span className="chip static">{data.summary.slow} slow (over {data.slow_threshold_ms} ms)</span>
              <span className="chip static">{data.summary.errors} failed</span>
              <span className="chip static">avg {formatMs(data.summary.avg_ms)}</span>
              <span className="chip static">max {formatMs(data.summary.max_ms)}</span>
            </div>
            {data.logs.length === 0 ? (
              <p className="muted">No statements match.</p>
            ) : (
              <div className="table-wrap">
                <table className="data-table log-table">
                  <thead>
                    <tr>
                      <th>Time</th>
                      <th>SQL</th>
                      <th className="num">Duration</th>
                      <th className="num">Rows</th>
                      <th>Request ID</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.logs.map((row) => (
                      <tr key={row.id}>
                        <td>{formatDateTime(row.ts)}</td>
                        <td className="wrap sql-cell">
                          <code>{row.sql}</code>
                          {row.error && <Badge tone="danger">{row.error}</Badge>}
                        </td>
                        <td className={`num${row.slow ? " is-slow" : ""}`}>{formatMs(row.duration_ms)}</td>
                        <td className="num">{row.rows ?? "-"}</td>
                        <td>
                          <code>{row.request_id}</code>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}
      </Loadable>
    </>
  );
}

function AuditView() {
  const [offset, setOffset] = useState(0);
  const state = useLoad(() => adminAuditLogs({ limit: PAGE, offset }), [offset]);
  return (
    <Loadable state={state}>
      {(data) =>
        data.logs.length === 0 && offset === 0 ? (
          <p className="muted">No administrator actions recorded yet.</p>
        ) : (
          <>
            <div className="table-wrap">
              <table className="data-table log-table">
                <thead>
                  <tr>
                    <th>Time</th>
                    <th>Administrator</th>
                    <th>Action</th>
                    <th>Target</th>
                    <th>Detail</th>
                    <th>IP</th>
                  </tr>
                </thead>
                <tbody>
                  {data.logs.map((row) => (
                    <tr key={row.id}>
                      <td>{formatDateTime(row.ts)}</td>
                      <td>{row.actor_email}</td>
                      <td>
                        <code>{row.action}</code>
                      </td>
                      <td className="wrap">{row.target || "-"}</td>
                      <td className="wrap">{row.detail || "-"}</td>
                      <td>{row.ip}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pager total={data.logs.length === PAGE ? offset + PAGE + 1 : offset + data.logs.length} offset={offset} limit={PAGE} onChange={setOffset} />
          </>
        )
      }
    </Loadable>
  );
}

export function LogsTab() {
  const [view, setView] = useState<View>("requests");
  return (
    <Card>
      <div className="segmented" role="tablist" aria-label="Log type">
        {VIEWS.map((item) => (
          <button key={item.id} type="button" role="tab" aria-selected={view === item.id} className={view === item.id ? "is-active" : ""} onClick={() => setView(item.id)}>
            {item.label}
          </button>
        ))}
      </div>
      {view === "requests" && <RequestsView />}
      {view === "sql" && <SqlView />}
      {view === "audit" && <AuditView />}
    </Card>
  );
}
