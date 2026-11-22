# 03 - Frontend

> **Status:** this document is the **baseline audit** of the code before remediation. Most findings referenced here are now fixed; see [13_REMEDIATION_REPORT.md](13_REMEDIATION_REPORT.md) for the current status and evidence.

Single route `/` rendering `templates/index.html`; logic in `static/script.js`
(361 lines), styling in `static/style.css` (1158 lines, CSS variables,
breakpoints at 820px/600px, reduced-motion and print rules).

## Sections (page-by-page)

| Section | Purpose | Components | API | Data shown | User actions |
|---|---|---|---|---|---|
| Topbar | Brand, new trip | brand link, "New trip" | none | static label "Local workspace" | `startNewTrip()` clears state + `localStorage` |
| Hero | Marketing | copy + note | none | static | none |
| 01 Planner | Collect request | textarea, counter, 3 quick prompts, submit + spinner | `POST /api/travel` | char count | type, pick prompt, Ctrl+Enter, submit |
| 02 Workflow | Show supervisor outcome | 3-step stepper, guardrail badge, reasoning, agent chips | reads response | `guardrail_*`, `selected_agents`, `supervisor_reasoning`, `requires_approval` | none |
| 03 Result | Show draft/final plan | markdown box, thread id | from response | `itinerary` or `answer` | Copy, Download PDF (html2pdf) |
| 04 Approval | HITL decision | feedback textarea, approve/revise | `POST /api/travel/approve` | `approval_request` | approve, request changes (feedback required) |
| Error box | Failures | `role="alert"` | n/a | error message | none |

## State and flow

- Globals: `currentThreadId` (also `localStorage["travel_thread_id"]`),
  `latestAnswerMarkdown`, `waitingForApproval`.
- `sendMessage()` blocks while `waitingForApproval`, validates non-empty
  input, posts `{message, thread_id}`, then shows workflow + draft + approval.
- `submitApproval(approved)` requires feedback when rejecting.
- Loading: buttons disabled; spinner only for draft mode.
- Responsive: yes. Accessibility: `aria-live`, `aria-current`, labels present.

## Frontend observations

- `renderMarkdown` assigns `marked.parse()` output to `innerHTML` with no
  sanitiser (`script.js:82`) - F-03.
- `waitingForApproval` is memory-only while `thread_id` persists, so a reload
  during review loses the draft UI and the pending interrupt becomes
  unreachable - F-18.
- CDN scripts have no integrity hashes; `marked` is unpinned
  (`index.html:182-183`) - F-10.
- Footer/topbar text is static ("Local workspace") in production - F-26.
- All DOM IDs used by the script exist in the template (verified).
