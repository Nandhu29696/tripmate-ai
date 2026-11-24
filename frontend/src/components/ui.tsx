import { useId, useState, type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode, type TextareaHTMLAttributes } from "react";
import { passwordStrength } from "../utils/format";
import { Icon } from "./Icon";

export function Spinner({ size = 18 }: { size?: number }) {
  return <span className="spinner" style={{ width: size, height: size }} role="status" aria-label="Loading" />;
}

type Variant = "primary" | "secondary" | "ghost" | "danger";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  loading?: boolean;
  block?: boolean;
}

export function Button({ variant = "primary", loading = false, block = false, disabled, children, className = "", ...rest }: ButtonProps) {
  return (
    <button
      {...rest}
      type={rest.type ?? "button"}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={`btn btn-${variant}${block ? " btn-block" : ""} ${className}`.trim()}
    >
      {loading && <Spinner size={16} />}
      {children}
    </button>
  );
}

interface FieldProps extends InputHTMLAttributes<HTMLInputElement> {
  label: string;
  error?: string;
  hint?: string;
}

export function Field({ label, error, hint, id, ...rest }: FieldProps) {
  const generated = useId();
  const fieldId = id ?? generated;
  const describedBy = error ? `${fieldId}-error` : hint ? `${fieldId}-hint` : undefined;
  return (
    <div className="field">
      <label htmlFor={fieldId}>{label}</label>
      <input id={fieldId} aria-invalid={error ? true : undefined} aria-describedby={describedBy} {...rest} />
      {error ? (
        <p id={`${fieldId}-error`} className="field-error" role="alert">
          {error}
        </p>
      ) : hint ? (
        <p id={`${fieldId}-hint`} className="field-hint">
          {hint}
        </p>
      ) : null}
    </div>
  );
}

const STRENGTH_LABEL = ["", "Too short", "Fair", "Good", "Strong"];

export function PasswordField({ label, showStrength = false, error, hint, value, ...rest }: Omit<FieldProps, "type"> & { showStrength?: boolean }) {
  const [visible, setVisible] = useState(false);
  const id = useId();
  const strength = showStrength ? passwordStrength(String(value ?? "")) : 0;
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <div className="input-affix">
        <input id={id} type={visible ? "text" : "password"} value={value} aria-invalid={error ? true : undefined} {...rest} />
        <button type="button" className="icon-btn" aria-label={visible ? "Hide password" : "Show password"} onClick={() => setVisible((v) => !v)}>
          <Icon name={visible ? "eyeOff" : "eye"} size={18} />
        </button>
      </div>
      {showStrength && strength > 0 && (
        <div className="strength" aria-live="polite">
          <div className={`strength-bar level-${strength}`}>
            <span />
            <span />
            <span />
            <span />
          </div>
          <span className="field-hint">{STRENGTH_LABEL[strength]}</span>
        </div>
      )}
      {error ? (
        <p className="field-error" role="alert">
          {error}
        </p>
      ) : hint ? (
        <p className="field-hint">{hint}</p>
      ) : null}
    </div>
  );
}

interface TextAreaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  label: string;
  counter?: boolean;
}

export function TextArea({ label, counter = false, id, value, maxLength, ...rest }: TextAreaProps) {
  const generated = useId();
  const fieldId = id ?? generated;
  return (
    <div className="field">
      <label htmlFor={fieldId}>{label}</label>
      <textarea id={fieldId} value={value} maxLength={maxLength} {...rest} />
      {counter && (
        <p className="field-hint counter" aria-live="polite">
          {String(value ?? "").length}
          {maxLength ? ` / ${maxLength}` : ""} characters
        </p>
      )}
    </div>
  );
}

type BadgeTone = "neutral" | "brand" | "success" | "warning" | "danger";

export function Badge({ tone = "neutral", children }: { tone?: BadgeTone; children: ReactNode }) {
  return <span className={`badge badge-${tone}`}>{children}</span>;
}

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <section className={`card ${className}`.trim()}>{children}</section>;
}

export function Skeleton({ lines = 3 }: { lines?: number }) {
  return (
    <div className="skeleton-block" aria-hidden="true">
      {Array.from({ length: lines }, (_, i) => (
        <span key={i} className="skeleton" style={{ width: `${95 - i * 12}%` }} />
      ))}
    </div>
  );
}
