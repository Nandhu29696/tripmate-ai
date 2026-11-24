import { useEffect, useRef, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError } from "../api/client";
import * as endpoints from "../api/endpoints";
import { Icon, type IconName } from "../components/Icon";
import { ProgressSteps } from "../components/ProgressSteps";
import { Button, Card, TextArea } from "../components/ui";
import { useAuth } from "../context/AuthContext";
import { useTrips } from "../context/TripsContext";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { useProgress } from "../hooks/useProgress";
import { firstName } from "../utils/format";

const MAX_CHARS = 4000;

const SUGGESTIONS = [
  { label: "Japan in autumn", prompt: "Plan a 7-day Japan trip from Dhaka in October for two people, including food, culture, and a mid-range budget." },
  { label: "Dubai city break", prompt: "Plan a 5-day Dubai trip from Dhaka with comfortable hotels, local food, and a mix of city highlights and relaxing time." },
  { label: "Thailand escape", prompt: "Plan a 7-day Thailand trip from Bangladesh with beaches, local food, budget-friendly stays, and relaxed sightseeing." },
];

const HOW: { icon: IconName; title: string; text: string }[] = [
  { icon: "sparkles", title: "Describe your trip", text: "Where, when, budget and what you love." },
  { icon: "users", title: "Agents do the research", text: "Flights, hotels, weather and costs, in parallel." },
  { icon: "check", title: "You review and approve", text: "Ask for changes until it feels right." },
];

export function NewTripPage() {
  useDocumentTitle("New trip");
  const { user } = useAuth();
  const { refresh } = useTrips();
  const navigate = useNavigate();
  const { steps, onProgress, reset } = useProgress();

  const [message, setMessage] = useState("");
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  const abort = useRef<AbortController | null>(null);

  // Stop reading the stream if the user leaves; the server still finishes and saves the plan.
  useEffect(() => () => abort.current?.abort(), []);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const text = message.trim();
    if (!text) {
      setError("Tell us a little about the trip you have in mind.");
      return;
    }

    setError("");
    reset();
    setRunning(true);
    abort.current = new AbortController();
    try {
      const trip = await endpoints.startTrip(text, onProgress, abort.current.signal);
      void refresh();
      navigate(`/trips/${trip.thread_id}`, { state: { trip } });
    } catch (caught) {
      if (caught instanceof DOMException && caught.name === "AbortError") return;
      if (caught instanceof ApiError) {
        const wait = caught.retryAfter ? ` Try again in about ${Math.max(1, Math.ceil(caught.retryAfter / 60))} min.` : "";
        setError(caught.message + (caught.status === 429 ? wait : ""));
      } else {
        setError("Something went wrong. Please try again.");
      }
      void refresh();
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="page narrow">
      <header className="page-head">
        <div>
          <h1>Where to next, {firstName(user?.name ?? "")}?</h1>
          <p className="muted">Describe your ideal trip. Your travel team will draft a plan for you to review.</p>
        </div>
      </header>

      {running ? (
        <ProgressSteps steps={steps} />
      ) : (
        <Card>
          <form onSubmit={(event) => void submit(event)} className="form-stack" noValidate>
            {error && (
              <div className="banner banner-error" role="alert">
                <Icon name="alert" size={18} /> {error}
              </div>
            )}
            <TextArea
              label="Describe your trip"
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              maxLength={MAX_CHARS}
              rows={6}
              counter
              placeholder="A week in Japan this fall, flying from Dhaka. We love food, quiet neighborhoods, and a mid-range budget…"
              onKeyDown={(e) => {
                if ((e.ctrlKey || e.metaKey) && e.key === "Enter") void submit(e as unknown as FormEvent);
              }}
            />

            <div>
              <p className="eyebrow">Need a spark?</p>
              <div className="chips">
                {SUGGESTIONS.map((item) => (
                  <button key={item.label} type="button" className="chip" onClick={() => setMessage(item.prompt)}>
                    <Icon name="compass" size={16} /> {item.label}
                  </button>
                ))}
              </div>
            </div>

            <div className="form-actions">
              <span className="muted small">Tip: press Ctrl + Enter to send</span>
              <Button type="submit">
                Create my draft <Icon name="arrow" size={18} />
              </Button>
            </div>
          </form>
        </Card>
      )}

      {!running && (
        <ul className="how-grid" aria-label="How it works">
          {HOW.map((item, index) => (
            <li key={item.title}>
              <span className="how-num">{index + 1}</span>
              <Icon name={item.icon} size={20} />
              <strong>{item.title}</strong>
              <span className="muted small">{item.text}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
