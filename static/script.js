"use strict";

const THREAD_KEY = "travel_thread_id";

let currentThreadId = null;
let latestAnswerMarkdown = "";
let waitingForApproval = false;

try {
  currentThreadId = localStorage.getItem(THREAD_KEY);
} catch (_) {
  currentThreadId = null;
}

const AGENT_LABELS = {
  flight_agent: "✈️ Flight Agent",
  hotel_agent: "🏨 Hotel Agent",
  weather_agent: "🌦️ Weather Agent",
  budget_agent: "💰 Budget Agent",
  itinerary_agent: "🗓️ Itinerary Agent"
};

const $ = (id) => document.getElementById(id);

function rememberThread(id) {
  currentThreadId = id || null;
  try {
    if (id) localStorage.setItem(THREAD_KEY, id);
    else localStorage.removeItem(THREAD_KEY);
  } catch (_) { /* storage unavailable */ }
}

// ---------------------------------------------------------------------------
// API helper: JSON in/out, same-origin cookies, central 401 handling
// ---------------------------------------------------------------------------
async function api(path, options = {}) {
  const response = await fetch(path, {
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    ...options
  });

  let data = {};
  try {
    data = await response.json();
  } catch (_) { /* non-JSON error body */ }

  if (response.status === 401 && data.auth_required) {
    showLogin();
  }
  if (!response.ok || data.success === false) {
    const error = new Error(data.error || "Something went wrong.");
    error.status = response.status;
    throw error;
  }
  return data;
}

// ---------------------------------------------------------------------------
// Small UI helpers
// ---------------------------------------------------------------------------
function setPrompt(text) {
  const input = $("userInput");
  input.value = text;
  updatePromptCount();
  input.focus();
}

function updatePromptCount() {
  const count = $("userInput").value.length;
  $("promptCount").textContent = `${count} ${count === 1 ? "character" : "characters"}`;
}

function setLoading(isLoading, mode = "draft") {
  $("sendBtn").disabled = isLoading;
  $("approveBtn").disabled = isLoading;
  $("reviseBtn").disabled = isLoading;

  if (isLoading && mode === "draft") {
    $("btnText").classList.add("hidden");
    $("btnLoader").classList.remove("hidden");
  } else {
    $("btnText").classList.remove("hidden");
    $("btnLoader").classList.add("hidden");
  }
}

function showError(message) {
  const box = $("errorBox");
  box.textContent = message;
  box.classList.remove("hidden");
  box.scrollIntoView({ behavior: "smooth", block: "center" });
}

function hideError() {
  const box = $("errorBox");
  box.classList.add("hidden");
  box.textContent = "";
}

// Model output and tool content are untrusted: always sanitize before HTML.
if (typeof DOMPurify !== "undefined") {
  DOMPurify.addHook("afterSanitizeAttributes", (node) => {
    if (node.tagName === "A") {
      node.setAttribute("target", "_blank");
      node.setAttribute("rel", "noopener noreferrer");
    }
  });
}

function renderMarkdown(element, markdown) {
  const text = markdown || "";
  if (typeof marked !== "undefined" && typeof DOMPurify !== "undefined") {
    element.innerHTML = DOMPurify.sanitize(marked.parse(text));
  } else {
    element.textContent = text;
  }
}

// ---------------------------------------------------------------------------
// Auth
// ---------------------------------------------------------------------------
function showLogin() {
  $("loginSection").classList.remove("hidden");
  $("plannerSection").classList.add("hidden");
  $("tripsSection").classList.add("hidden");
  $("logoutBtn").classList.add("hidden");
}

function showApp(authRequired) {
  $("loginSection").classList.add("hidden");
  $("plannerSection").classList.remove("hidden");
  $("logoutBtn").classList.toggle("hidden", !authRequired);
}

async function login() {
  const key = $("accessKey").value;
  $("loginMessage").textContent = "";

  if (!key.trim()) {
    $("loginMessage").textContent = "Please enter your access key.";
    return;
  }

  $("loginBtn").disabled = true;
  try {
    await api("/api/session", { method: "POST", body: JSON.stringify({ access_key: key }) });
    $("accessKey").value = "";
    await bootstrap();
  } catch (error) {
    $("loginMessage").textContent = error.message;
  } finally {
    $("loginBtn").disabled = false;
  }
}

async function logout() {
  try {
    await api("/api/session", { method: "DELETE" });
  } catch (_) { /* ignore */ }
  rememberThread(null);
  resetTripView();
  showLogin();
}

// ---------------------------------------------------------------------------
// Trips list, restore, delete
// ---------------------------------------------------------------------------
const STATUS_TEXT = {
  awaiting_approval: "Waiting for your review",
  completed: "Final plan ready",
  blocked: "Outside travel scope",
  failed: "Did not finish",
  running: "In progress"
};

async function loadTrips() {
  try {
    const data = await api("/api/travel/threads");
    renderTrips(data.trips || []);
  } catch (_) {
    $("tripsSection").classList.add("hidden");
  }
}

function renderTrips(trips) {
  const list = $("tripList");
  list.textContent = "";
  $("tripsSection").classList.toggle("hidden", trips.length === 0);

  trips.forEach((trip) => {
    const item = document.createElement("li");
    item.className = "trip-item";

    const info = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = trip.title || "Untitled trip";
    const meta = document.createElement("span");
    const when = new Date(trip.updated_at);
    meta.textContent = `${STATUS_TEXT[trip.status] || trip.status} · ${
      isNaN(when) ? "" : when.toLocaleString()
    }`;
    info.append(title, meta);

    const actions = document.createElement("div");
    actions.className = "trip-actions";

    const open = document.createElement("button");
    open.type = "button";
    open.dataset.action = "open-trip";
    open.dataset.threadId = trip.thread_id;
    open.textContent = "Open";

    const del = document.createElement("button");
    del.type = "button";
    del.className = "danger-btn";
    del.dataset.action = "delete-trip";
    del.dataset.threadId = trip.thread_id;
    del.textContent = "Delete";

    actions.append(open, del);
    item.append(info, actions);
    list.appendChild(item);
  });
}

async function openTrip(threadId, quiet = false) {
  hideError();
  try {
    const data = await api(`/api/travel/${encodeURIComponent(threadId)}`);
    rememberThread(data.thread_id);
    renderTrip(data, !quiet);
  } catch (error) {
    if (error.status === 404) {
      if (threadId === currentThreadId) rememberThread(null);
      if (!quiet) showError("That trip is no longer available.");
    } else if (!quiet) {
      showError(error.message);
    }
  }
}

async function deleteTrip(threadId) {
  if (!window.confirm("Delete this trip and its saved plan? This cannot be undone.")) return;

  try {
    await api(`/api/travel/${encodeURIComponent(threadId)}`, { method: "DELETE" });
    if (threadId === currentThreadId) {
      rememberThread(null);
      resetTripView();
    }
    await loadTrips();
  } catch (error) {
    showError(error.message);
  }
}

// ---------------------------------------------------------------------------
// Rendering a trip
// ---------------------------------------------------------------------------
function showWorkflow(data) {
  const section = $("workflowSection");
  const chips = $("agentChips");
  const badge = $("guardrailBadge");
  const steps = section.querySelectorAll(".workflow-step");

  $("supervisorReasoning").textContent = data.supervisor_reasoning || "Supervisor routing completed.";
  chips.textContent = "";

  (data.selected_agents || []).forEach((agent) => {
    const chip = document.createElement("span");
    chip.className = "agent-chip";
    chip.textContent = AGENT_LABELS[agent] || agent;
    chips.appendChild(chip);
  });

  const blocked = data.guardrail_allowed === false;
  badge.textContent = blocked ? "Outside travel scope" : "Travel scope checked";
  badge.classList.toggle("blocked", blocked);
  badge.classList.remove("fallback");

  steps.forEach((step) => {
    step.classList.remove("is-complete", "is-current", "is-blocked");
    step.removeAttribute("aria-current");
  });

  steps[0].classList.add("is-complete");
  if (blocked) {
    steps[1].classList.add("is-blocked");
  } else {
    steps[1].classList.add("is-complete");
    if (data.requires_approval) {
      steps[2].classList.add("is-current");
      steps[2].setAttribute("aria-current", "step");
    } else {
      steps[2].classList.add("is-complete");
    }
  }

  section.classList.remove("hidden");
}

function showResult(answer, data, isDraft, scroll = true) {
  latestAnswerMarkdown = answer || "";
  renderMarkdown($("resultBox"), latestAnswerMarkdown);

  let info = `Trip reference: ${data.thread_id}`;
  if (isDraft && data.revision_count > 0) {
    info += ` · Revision ${data.revision_count} of ${data.max_revisions}`;
  }
  $("threadInfo").textContent = info;
  $("resultTitle").textContent = isDraft ? "Draft Travel Plan" : "Your Final AI Travel Plan";
  $("resultSection").classList.remove("hidden");

  if (scroll) {
    $("resultSection").scrollIntoView({ behavior: "smooth", block: "start" });
  }
}

function showApproval(data) {
  waitingForApproval = true;
  $("approvalRequest").textContent =
    data.approval_request || "Approve the draft or provide feedback before the final plan is generated.";
  $("approvalSection").classList.remove("hidden");
}

function hideApproval() {
  waitingForApproval = false;
  $("approvalSection").classList.add("hidden");
  $("approvalFeedback").value = "";
}

function renderTrip(data, scroll = true) {
  showWorkflow(data);
  $("userInput").value = data.user_query || $("userInput").value;
  updatePromptCount();

  if (data.requires_approval) {
    showResult(data.itinerary || data.answer, data, true, scroll);
    showApproval(data);
  } else {
    hideApproval();
    showResult(data.answer, data, false, scroll);
  }
}

function resetTripView() {
  latestAnswerMarkdown = "";
  waitingForApproval = false;
  $("userInput").value = "";
  $("workflowSection").classList.add("hidden");
  $("resultSection").classList.add("hidden");
  $("approvalSection").classList.add("hidden");
  $("approvalFeedback").value = "";
  hideError();
  updatePromptCount();
}

function startNewTrip() {
  if (waitingForApproval && !window.confirm("You have a draft waiting for review. Start a new trip? The draft stays saved under 'Your trips'.")) {
    return;
  }
  rememberThread(null);
  resetTripView();
  $("userInput").focus();
}

// ---------------------------------------------------------------------------
// Live progress (NDJSON stream from the server)
// ---------------------------------------------------------------------------
function startProgress() {
  $("progressList").textContent = "";
  $("progressSection").classList.remove("hidden");
  $("progressSection").scrollIntoView({ behavior: "smooth", block: "center" });
}

function endProgress() {
  $("progressSection").classList.add("hidden");
}

function handleProgress(event) {
  const list = $("progressList");
  let item = Array.from(list.children).find((li) => li.dataset.node === event.node);

  if (!item) {
    item = document.createElement("li");
    item.className = "progress-step";
    item.dataset.node = event.node;
    const icon = document.createElement("span");
    icon.className = "step-icon";
    icon.setAttribute("aria-hidden", "true");
    const text = document.createElement("span");
    text.className = "step-text";
    item.append(icon, text);
    list.appendChild(item);
  }

  // Keep the label from the "start" event: a finish event for a revision would
  // otherwise flip "Revising your itinerary" back to "Drafting your itinerary".
  if (event.state === "start" || !item.querySelector(".step-text").textContent) {
    item.querySelector(".step-text").textContent = event.label;
  }
  const icon = item.querySelector(".step-icon");
  item.classList.remove("is-active", "is-done", "is-failed");

  if (event.state === "start") {
    item.classList.add("is-active");
    icon.textContent = "";
  } else if (event.state === "done") {
    item.classList.add("is-done");
    icon.textContent = "✓";
  } else {
    item.classList.add("is-failed");
    icon.textContent = "!";
  }
}

// POST that returns newline-delimited JSON events: progress..., then result|error.
async function streamRequest(path, payload, onProgress) {
  const response = await fetch(path, {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });

  if (!response.ok) {
    // Checks done before the stream opens (401, 400, 404, 409, 429) are plain JSON.
    let data = {};
    try {
      data = await response.json();
    } catch (_) { /* non-JSON body */ }
    if (response.status === 401 && data.auth_required) showLogin();
    const error = new Error(data.error || "Something went wrong.");
    error.status = response.status;
    throw error;
  }

  let result = null;
  const handleLine = (line) => {
    if (!line.trim()) return;
    let event;
    try {
      event = JSON.parse(line);
    } catch (_) {
      return;
    }
    if (event.type === "progress") {
      onProgress(event);
    } else if (event.type === "result") {
      result = event;
    } else if (event.type === "error") {
      const error = new Error(event.error || "Something went wrong.");
      error.status = event.status;
      throw error;
    }
  };

  if (response.body && response.body.getReader) {
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let newline;
      while ((newline = buffer.indexOf("\n")) >= 0) {
        handleLine(buffer.slice(0, newline));
        buffer = buffer.slice(newline + 1);
      }
    }
    handleLine(buffer + decoder.decode());
  } else {
    // No streaming support: same events, just delivered at the end.
    (await response.text()).split("\n").forEach(handleLine);
  }

  if (!result) {
    loadTrips();
    throw new Error("The connection was interrupted. If your plan finished, it is saved under Your trips.");
  }
  return result;
}

// ---------------------------------------------------------------------------
// Actions
// ---------------------------------------------------------------------------
async function sendMessage() {
  hideError();

  if (waitingForApproval) {
    showError("Please approve or revise the current draft before starting another plan.");
    return;
  }

  const message = $("userInput").value.trim();
  if (!message) {
    showError("Please enter your travel request first.");
    return;
  }

  setLoading(true, "draft");
  startProgress();
  try {
    const data = await streamRequest("/api/travel/stream", { message }, handleProgress);
    endProgress();
    rememberThread(data.thread_id);
    renderTrip(data);
    loadTrips();
  } catch (error) {
    endProgress();
    showError(error.message);
  } finally {
    setLoading(false, "draft");
  }
}

async function submitApproval(approved) {
  hideError();

  if (!currentThreadId || !waitingForApproval) {
    showError("There is no draft waiting for approval.");
    return;
  }

  const feedback = $("approvalFeedback").value.trim();
  if (!approved && !feedback) {
    showError("Please enter revision feedback before requesting changes.");
    $("approvalFeedback").focus();
    return;
  }

  setLoading(true, "approval");
  startProgress();
  try {
    const data = await streamRequest(
      "/api/travel/approve/stream",
      { thread_id: currentThreadId, approved, feedback },
      handleProgress
    );
    endProgress();
    // A rejection returns a revised draft that needs another review.
    renderTrip(data);
    loadTrips();
  } catch (error) {
    endProgress();
    showError(error.message);
  } finally {
    setLoading(false, "approval");
  }
}

function copyResult() {
  const text = $("resultBox").innerText;
  if (!text) return;

  navigator.clipboard.writeText(text)
    .then(() => {
      const button = document.querySelector('[data-action="copy"]');
      const old = button.textContent;
      button.textContent = "Copied!";
      setTimeout(() => { button.textContent = old; }, 1400);
    })
    .catch(() => showError("Could not copy result."));
}

function downloadPDF() {
  const pdfContent = $("pdfContent");
  if (!latestAnswerMarkdown || !pdfContent) {
    showError("No travel plan available to download.");
    return;
  }

  const button = document.querySelector('[data-action="pdf"]');
  const old = button.textContent;
  button.textContent = "Preparing PDF...";
  button.disabled = true;

  const restore = () => { button.textContent = old; button.disabled = false; };

  html2pdf()
    .set({
      margin: 0.5,
      filename: "ai-travel-plan.pdf",
      image: { type: "jpeg", quality: 0.98 },
      html2canvas: { scale: 2, useCORS: true, backgroundColor: "#ffffff" },
      jsPDF: { unit: "in", format: "a4", orientation: "portrait" },
      pagebreak: { mode: ["avoid-all", "css", "legacy"] }
    })
    .from(pdfContent)
    .save()
    .then(restore)
    .catch(() => { restore(); showError("Could not download PDF."); });
}

// ---------------------------------------------------------------------------
// Event wiring (no inline handlers: required by the Content-Security-Policy)
// ---------------------------------------------------------------------------
document.addEventListener("click", (event) => {
  const el = event.target.closest("[data-action]");
  if (!el) return;

  switch (el.dataset.action) {
    case "new-trip": startNewTrip(); break;
    case "set-prompt": setPrompt(el.dataset.prompt || ""); break;
    case "send": sendMessage(); break;
    case "copy": copyResult(); break;
    case "pdf": downloadPDF(); break;
    case "approve": submitApproval(true); break;
    case "revise": submitApproval(false); break;
    case "login": login(); break;
    case "logout": logout(); break;
    case "open-trip": openTrip(el.dataset.threadId); break;
    case "delete-trip": deleteTrip(el.dataset.threadId); break;
  }
});

document.addEventListener("keydown", (event) => {
  if (event.ctrlKey && event.key === "Enter" && document.activeElement === $("userInput")) {
    sendMessage();
  }
  if (event.key === "Enter" && document.activeElement === $("accessKey")) {
    login();
  }
});

$("userInput").addEventListener("input", updatePromptCount);
updatePromptCount();

async function bootstrap() {
  try {
    const session = await api("/api/session");
    if (!session.authenticated) {
      showLogin();
      return;
    }
    showApp(session.auth_required);
  } catch (error) {
    showError(error.message);
    return;
  }

  await loadTrips();
  if (currentThreadId) {
    await openTrip(currentThreadId, true);
  }
}

bootstrap();
