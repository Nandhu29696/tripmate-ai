import { useEffect } from "react";

export function useDocumentTitle(title: string): void {
  useEffect(() => {
    const previous = document.title;
    document.title = title ? `${title} · TripMate AI` : "TripMate AI";
    return () => {
      document.title = previous;
    };
  }, [title]);
}
