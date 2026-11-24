# 03 - Frontend (React, rewritten)

> This replaces the original description of the vanilla-JS page. The old
> `templates/` and `static/` files were removed.

**Stack:** React 19, TypeScript (strict, `noUncheckedIndexedAccess`), Vite, React
Router 7, `react-markdown` + `remark-gfm`. No UI kit: a hand-written CSS design
system (tokens, light/dark, responsive, print). Tests: Vitest + Testing Library.
Production build: about 145 KB gzipped JavaScript, no inline scripts.

## Structure

```
frontend/src/
  api/         types.ts, client.ts (fetch wrapper, ApiError, central 401 hook),
               stream.ts (NDJSON reader), endpoints.ts (one function per API call)
  context/     AuthContext (session state), TripsContext (sidebar list), ToastContext
  hooks/       useProgress (streamed steps), useTheme, useDocumentTitle
  components/  ui.tsx (Button, Field, PasswordField, TextArea, Badge, Card, Skeleton),
               Markdown, ProgressSteps, ConfirmDialog, RouteGuards, Logo, Icon
  layouts/     AuthLayout (brand panel + card), AppLayout (sidebar, mobile drawer)
  pages/       Login, Forgot, Reset, NewTrip, Trip, Account, NotFound
  utils/       format.ts, urlParams.ts
  styles.css   design system
```

## Routes

| Route | Access | Purpose |
|---|---|---|
| `/login` (`?mode=signup`) | public | Sign in / create account, Google button (only if configured), strength meter |
| `/forgot` | public | Request a reset link; same message for every address |
| `/reset?token=` | public | Choose a new password; signs in on success |
| `/` | signed in | New trip: description box, suggestions, how-it-works |
| `/trips/:id` | signed in | Plan, trip team, review panel, copy / Save as PDF / delete |
| `/account` | signed in | Profile, sign-in methods, delete account |
| `*` | any | Friendly 404 |

## Authentication behaviour

- `AuthProvider` loads `GET /api/session` once; status is `loading | authenticated | anonymous | error`.
- `RequireAuth` redirects signed-out visitors to `/login` and remembers the page they asked for;
  `RedirectIfAuthed` sends signed-in visitors back to that page (only in-app paths are honoured).
- Any API 401 flagged `auth_required` calls a registered handler that signs the user out of the UI,
  so an expired or revoked session lands on `/login` from anywhere.
- Email and Google links arrive at `/?reset=`, `/?verified=1`, `/?auth_error=`; `bootstrapUrl()` rewrites
  the address bar before React renders (so a guard cannot discard the parameters) and queues a toast.

## Trip lifecycle in the UI

New trip -> `POST /api/travel/stream` -> checklist updates per event (agents run in parallel, so several
steps are active together) -> navigate to `/trips/:id` with the result as a first paint -> the page always
revalidates from the server (navigation state survives reloads and can be stale) and ignores a late
response once the user has acted -> review: approve, or request changes (feedback required) -> a revised
draft returns for another review until the revision limit, then the final plan.

## Security and quality properties

- Model output goes through `react-markdown`: no raw HTML, `javascript:` URLs dropped, links open with
  `rel="noopener noreferrer"`, tables scroll inside a wrapper. Verified by tests with hostile input.
- The build has no inline scripts, so the strict CSP (`script-src 'self'`) stays in force; fonts are system fonts.
- Accessibility: skip link, labelled inputs with `aria-invalid`/error text, `aria-live` for progress and toasts,
  `role="dialog"` with Escape and focus on the safe action, a closed mobile drawer that is `visibility: hidden`
  (not merely off-screen, so keyboards cannot reach it), `prefers-reduced-motion` respected.
- Layout: long unbroken text (URLs, code) wraps or scrolls inside its box; verified at 390 px with worst-case content.
- Print: "Save as PDF" uses the browser print dialog with a stylesheet that prints only the plan.

## v2.2 additions

- `components/TripPlan.tsx` + `utils/itinerary.ts`: parse the planner's markdown into at-a-glance tiles, a weather outlook, day cards (weather chip, rows, cost footer), a day-jump bar and plain sections. Plans that contain no `## Day N` headings fall back to plain markdown, so older trips still render. Tested in `utils/itinerary.test.ts` and `admin.test.tsx`.
- Admin console under `/admin` (`pages/admin/`: Overview, Users, Trips, Logs, System) guarded by `RequireAdmin` (UI only; the server enforces access). `hooks/useLoad.ts` loads data, ignores stale responses and can poll.
- `styles-v22.css`: brand gradient, stat cards, request chart, timeline, tables, print rules for day cards.
- Tests: 101 (Vitest + Testing Library).
