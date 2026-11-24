import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { Button } from "./ui";

interface ConfirmDialogProps {
  open: boolean;
  title: string;
  children: ReactNode;
  confirmLabel: string;
  /** When set, the user must type this word before the confirm button enables. */
  requireText?: string;
  danger?: boolean;
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

export function ConfirmDialog({ open, title, children, confirmLabel, requireText, danger = false, busy = false, onConfirm, onCancel }: ConfirmDialogProps) {
  const titleId = useId();
  const cancelRef = useRef<HTMLButtonElement>(null);
  const [typed, setTyped] = useState("");

  useEffect(() => {
    if (!open) return;
    setTyped("");
    cancelRef.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !busy) onCancel();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, busy, onCancel]);

  if (!open) return null;

  const allowed = !requireText || typed.trim() === requireText;

  return (
    <div className="modal-backdrop" onMouseDown={(event) => event.target === event.currentTarget && !busy && onCancel()}>
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby={titleId}>
        <h2 id={titleId}>{title}</h2>
        <div className="modal-body">{children}</div>
        {requireText && (
          <div className="field">
            <label htmlFor={`${titleId}-confirm`}>
              Type <strong>{requireText}</strong> to confirm
            </label>
            <input id={`${titleId}-confirm`} value={typed} onChange={(event) => setTyped(event.target.value)} autoComplete="off" />
          </div>
        )}
        <div className="modal-actions">
          <button ref={cancelRef} type="button" className="btn btn-secondary" onClick={onCancel} disabled={busy}>
            Cancel
          </button>
          <Button variant={danger ? "danger" : "primary"} onClick={onConfirm} disabled={!allowed} loading={busy}>
            {confirmLabel}
          </Button>
        </div>
      </div>
    </div>
  );
}
