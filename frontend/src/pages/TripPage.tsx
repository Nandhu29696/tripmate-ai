import { useEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import { ApiError } from "../api/client";
import * as endpoints from "../api/endpoints";
import type { TripPayload } from "../api/types";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { Icon, type IconName } from "../components/Icon";
import { Markdown } from "../components/Markdown";
import { ProgressSteps } from "../components/ProgressSteps";
import { Badge, Button, Card, Skeleton, TextArea } from "../components/ui";
import { useToast } from "../context/ToastContext";
import { useTrips } from "../context/TripsContext";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { useProgress } from "../hooks/useProgress";
import { AGENT_LABEL, STATUS_LABEL } from "../utils/format";

const AGENT_ICON: Record<string, IconName> = {
  flight_agent: "plane",
  hotel_agent: "bed",
  weather_agent: "cloud",
  budget_agent: "wallet",
  itinerary_agent: "calendar",
};

function message(error: unknown): string {
  return error instanceof ApiError ? error.message : "Something went wrong. Please try again.";
}

export function TripPage() {
  const { threadId = "" } = useParams();
  const location = useLocation();
  const navigate = useNavigate();
  const toast = useToast();
  const { refresh, remove } = useTrips();
  const { steps, onProgress, reset } = useProgress();

  const handedOver = (location.state as { trip?: TripPayload } | null)?.trip;
  const [trip, setTrip] = useState<TripPayload | null>(handedOver?.thread_id === threadId ? handedOver : null);
  const [loadError, setLoadError] = useState("");
  const [feedback, setFeedback] = useState("");
  const [feedbackError, setFeedbackError] = useState("");
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState("");
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const abort = useRef<AbortController | null>(null);
  const acted = useRef(false); // true once the user starts a review on this page

  useDocumentTitle(trip ? trip.user_query.slice(0, 40) : "Trip");

  // The trip handed over by the previous page renders instantly, but it is only a first
  // paint: the router keeps navigation state across reloads, so it can be stale. Always
  // revalidate from the server, unless the user has already acted on this page.
  useEffect(() => {
    let cancelled = false;
    const haveFirstPaint = trip?.thread_id === threadId;
    if (!haveFirstPaint) {
      setTrip(null);
      setLoadError("");
    }
    endpoints
      .getTrip(threadId)
      .then((loaded) => {
        if (!cancelled && !acted.current) setTrip(loaded);
      })
      .catch((caught) => {
        if (cancelled || haveFirstPaint) return; // keep showing what we have
        setLoadError(caught instanceof ApiError && caught.status === 404 ? "We couldn't find that trip. It may have been deleted." : message(caught));
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [threadId]);

  useEffect(() => () => abort.current?.abort(), []);

  const review = async (approved: boolean) => {
    if (!trip) return;
    if (!approved && !feedback.trim()) {
      setFeedbackError("Tell us what you'd like to change before requesting a revision.");
      return;
    }

    setFeedbackError("");
    setRunError("");
    acted.current = true;
    reset();
    setRunning(true);
    abort.current = new AbortController();
    try {
      const next = await endpoints.reviewTrip({ thread_id: trip.thread_id, approved, feedback: feedback.trim() }, onProgress, abort.current.signal);
      setTrip(next);
      setFeedback("");
      void refresh();
      if (approved) toast.success("Your final plan is ready.");
      else toast.info(`Revision ${next.revision_count} of ${next.max_revisions} is ready for your review.`);
    } catch (caught) {
      if (caught instanceof DOMException && caught.name === "AbortError") return;
      setRunError(message(caught));
      void refresh();
    } finally {
      setRunning(false);
    }
  };

  const copyPlan = async () => {
    if (!trip) return;
    try {
      await navigator.clipboard.writeText(trip.requires_approval ? trip.itinerary : trip.answer);
      toast.success("Plan copied to your clipboard.");
    } catch {
      toast.error("Could not copy the plan. Select the text and copy it manually.");
    }
  };

  const deleteTrip = async () => {
    setDeleting(true);
    try {
      await remove(threadId);
      toast.success("Trip deleted.");
      navigate("/", { replace: true });
    } catch (caught) {
      toast.error(message(caught));
      setDeleting(false);
      setConfirmDelete(false);
    }
  };

  if (loadError) {
    return (
      <div className="page narrow">
        <Card className="empty-state">
          <Icon name="alert" size={28} />
          <h1>Trip not available</h1>
          <p className="muted">{loadError}</p>
          <Link to="/" className="btn btn-primary">
            Plan a new trip
          </Link>
        </Card>
      </div>
    );
  }

  if (!trip) {
    return (
      <div className="page">
        <Card>
          <Skeleton lines={5} />
        </Card>
      </div>
    );
  }

  const blocked = trip.status === "blocked";
  const awaiting = trip.requires_approval;
  const planText = awaiting ? trip.itinerary : trip.answer;
  const revisionsLeft = Math.max(0, trip.max_revisions - trip.revision_count);

  return (
    <div className="page">
      <header className="page-head no-print">
        <div className="page-head-main">
          <Link to="/" className="back-link">
            <Icon name="chevron" size={14} className="flip" /> New trip
          </Link>
          <h1 className="trip-title">{trip.user_query}</h1>
          <div className="meta-row">
            <Badge tone={blocked ? "neutral" : awaiting ? "warning" : "success"}>{STATUS_LABEL[trip.status]}</Badge>
            {trip.revision_count > 0 && (
              <Badge tone="brand">
                Revision {trip.revision_count} of {trip.max_revisions}
              </Badge>
            )}
          </div>
        </div>
        {!blocked && (
          <div className="page-actions">
            <Button variant="secondary" onClick={() => void copyPlan()}>
              <Icon name="copy" size={16} /> Copy
            </Button>
            <Button variant="secondary" onClick={() => window.print()}>
              <Icon name="printer" size={16} /> Save as PDF
            </Button>
            <Button variant="ghost" onClick={() => setConfirmDelete(true)} aria-label="Delete trip">
              <Icon name="trash" size={16} /> Delete
            </Button>
          </div>
        )}
      </header>

      {running && <ProgressSteps steps={steps} title={awaiting ? "Updating your plan" : "Working on your trip"} />}

      {runError && (
        <div className="banner banner-error no-print" role="alert">
          <Icon name="alert" size={18} /> {runError}
        </div>
      )}

      {blocked ? (
        <Card className="empty-state">
          <Icon name="info" size={28} />
          <h2>That's outside what TripMate can help with</h2>
          <p className="muted">{trip.answer}</p>
          <div className="row">
            <Link to="/" className="btn btn-primary">
              Plan a trip
            </Link>
            <Button variant="ghost" onClick={() => setConfirmDelete(true)}>
              <Icon name="trash" size={16} /> Delete
            </Button>
          </div>
        </Card>
      ) : (
        <div className="trip-grid">
          <article className="card plan print-area">
            <div className="plan-head">
              <h2 className="card-title">{awaiting ? "Draft itinerary" : "Your final plan"}</h2>
              <span className="muted small print-only">TripMate AI</span>
            </div>
            <Markdown>{planText}</Markdown>
          </article>

          <aside className="trip-side no-print">
            {awaiting && !running && (
              <Card className="review-card">
                <h2 className="card-title">Your review</h2>
                <p className="muted small">{trip.approval_request || "Approve the draft, or tell us what to change."}</p>
                <TextArea
                  label="Want to change anything?"
                  value={feedback}
                  onChange={(e) => {
                    setFeedback(e.target.value);
                    setFeedbackError("");
                  }}
                  maxLength={2000}
                  rows={4}
                  placeholder="For example: lower the hotel budget, add a slower day, include more local food…"
                />
                {feedbackError && (
                  <p className="field-error" role="alert">
                    {feedbackError}
                  </p>
                )}
                <div className="stack-sm">
                  <Button block onClick={() => void review(true)}>
                    <Icon name="check" size={16} /> Looks good, finalize
                  </Button>
                  <Button block variant="secondary" onClick={() => void review(false)}>
                    Request changes
                  </Button>
                </div>
                <p className="muted small center">
                  {revisionsLeft > 0 ? `${revisionsLeft} revision${revisionsLeft === 1 ? "" : "s"} left before we finalize.` : "This is the last revision; we'll finalize with your feedback."}
                </p>
              </Card>
            )}

            <Card>
              <h2 className="card-title">Your trip team</h2>
              <div className="chips">
                {trip.selected_agents.map((agent) => (
                  <span key={agent} className="chip static">
                    <Icon name={AGENT_ICON[agent] ?? "sparkles"} size={16} /> {AGENT_LABEL[agent] ?? agent}
                  </span>
                ))}
              </div>
              {trip.supervisor_reasoning && <p className="muted small">{trip.supervisor_reasoning}</p>}
              <Badge tone={trip.guardrail_allowed ? "success" : "neutral"}>{trip.guardrail_allowed ? "Travel scope checked" : "Outside travel scope"}</Badge>
            </Card>
          </aside>
        </div>
      )}

      <ConfirmDialog
        open={confirmDelete}
        title="Delete this trip?"
        confirmLabel="Delete trip"
        danger
        busy={deleting}
        onConfirm={() => void deleteTrip()}
        onCancel={() => setConfirmDelete(false)}
      >
        <p>This removes the trip and its saved plan. You can't undo this.</p>
      </ConfirmDialog>
    </div>
  );
}
