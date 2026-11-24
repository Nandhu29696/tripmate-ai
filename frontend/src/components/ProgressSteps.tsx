import type { RunStep } from "../hooks/useProgress";
import { Icon } from "./Icon";

/** Live checklist of the stages the server is working through. */
export function ProgressSteps({ steps, title = "Working on your trip" }: { steps: RunStep[]; title?: string }) {
  return (
    <section className="card progress-card" aria-live="polite" aria-label={title}>
      <h2 className="card-title">{title}</h2>
      <p className="muted small">This usually takes under a minute. You can leave this page; your plan is saved in your trips.</p>
      <ol className="steps">
        {steps.length === 0 && (
          <li className="step is-active">
            <span className="step-icon" />
            <span>Getting started</span>
          </li>
        )}
        {steps.map((step) => (
          <li key={step.node} className={`step is-${step.state === "start" ? "active" : step.state}`}>
            <span className="step-icon" aria-hidden="true">
              {step.state === "done" && <Icon name="check" size={12} />}
              {step.state === "failed" && "!"}
            </span>
            <span>{step.label}</span>
          </li>
        ))}
      </ol>
    </section>
  );
}
