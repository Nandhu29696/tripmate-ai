import { useState } from "react";
import { ApiError } from "../../api/client";
import { adminDeleteTrip, adminTrips } from "../../api/endpoints";
import type { AdminTrip, TripStatus } from "../../api/types";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { Icon } from "../../components/Icon";
import { Badge, Button, Card } from "../../components/ui";
import { useToast } from "../../context/ToastContext";
import { useLoad } from "../../hooks/useLoad";
import { formatDateTime, formatTokens, STATUS_LABEL } from "../../utils/format";
import { Loadable, Pager } from "./shared";

const PAGE = 25;
const TONE: Record<TripStatus, "brand" | "success" | "warning" | "danger" | "neutral"> = {
  awaiting_approval: "warning",
  completed: "success",
  blocked: "neutral",
  failed: "danger",
  running: "brand",
};

export function TripsTab() {
  const toast = useToast();
  const [status, setStatus] = useState("");
  const [offset, setOffset] = useState(0);
  const [toDelete, setToDelete] = useState<AdminTrip | null>(null);
  const [deleting, setDeleting] = useState(false);
  const state = useLoad(() => adminTrips({ status, limit: PAGE, offset }), [status, offset]);

  const remove = async () => {
    if (!toDelete) return;
    setDeleting(true);
    try {
      await adminDeleteTrip(toDelete.thread_id);
      toast.success("Trip deleted.");
      setToDelete(null);
      await state.reload();
    } catch (caught) {
      toast.error(caught instanceof ApiError ? caught.message : "Could not delete the trip.");
    } finally {
      setDeleting(false);
    }
  };

  return (
    <Card>
      <p className="muted small">Trip text is private to its owner. This list shows only who planned what and when.</p>
      <div className="toolbar">
        <label className="select-box">
          <span className="sr-only">Filter by status</span>
          <select
            value={status}
            onChange={(e) => {
              setStatus(e.target.value);
              setOffset(0);
            }}
          >
            <option value="">All statuses</option>
            {(Object.keys(STATUS_LABEL) as TripStatus[]).map((key) => (
              <option key={key} value={key}>
                {STATUS_LABEL[key]}
              </option>
            ))}
          </select>
        </label>
        <Button variant="secondary" onClick={() => void state.reload()}>
          <Icon name="refresh" size={16} /> Refresh
        </Button>
      </div>

      <Loadable state={state}>
        {(data) => (
          <>
            {data.trips.length === 0 ? (
              <p className="muted">No trips match.</p>
            ) : (
              <div className="table-wrap">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Trip request</th>
                      <th>Owner</th>
                      <th>Status</th>
                      <th className="num">AI tokens</th>
                      <th>Updated</th>
                      <th>
                        <span className="sr-only">Actions</span>
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.trips.map((trip) => (
                      <tr key={trip.thread_id}>
                        <td className="wrap">{trip.title || "Untitled"}</td>
                        <td>{trip.owner_email}</td>
                        <td>
                          <Badge tone={TONE[trip.status]}>{STATUS_LABEL[trip.status]}</Badge>
                        </td>
                        <td className="num" title={`${trip.input_tokens.toLocaleString()} in / ${trip.output_tokens.toLocaleString()} out, ${trip.llm_calls} AI calls`}>
                          {formatTokens(trip.input_tokens + trip.output_tokens)}
                          <span className="cell-sub">{trip.llm_calls} calls</span>
                        </td>
                        <td>{formatDateTime(trip.updated_at)}</td>
                        <td>
                          <Button variant="ghost" onClick={() => setToDelete(trip)} aria-label={`Delete trip ${trip.title}`}>
                            <Icon name="trash" size={16} />
                          </Button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <Pager total={data.total} offset={offset} limit={PAGE} onChange={setOffset} />
          </>
        )}
      </Loadable>

      <ConfirmDialog open={toDelete !== null} title="Delete this trip?" confirmLabel="Delete trip" danger busy={deleting} onCancel={() => setToDelete(null)} onConfirm={() => void remove()}>
        <p>
          This removes the trip and its saved plan for <strong>{toDelete?.owner_email}</strong>. It cannot be undone.
        </p>
      </ConfirmDialog>
    </Card>
  );
}
