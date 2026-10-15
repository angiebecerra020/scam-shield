/*
  app.js — Makes the dashboard page interactive.

  How it fits in: index.html loads this file. It:
    - asks our server "are you running?" (GET /health) and shows the answer
    - sends the sign-up form (POST /api/enrollments), which texts the senior
    - checks every few seconds whether the senior said YES
      (GET /api/enrollments/{id})
    - in demo mode, shows buttons that pretend to be the senior's phone
  Later it will show the live risk meter, reasons, source links and call history.
*/

// How often to check whether the senior answered (milliseconds).
const CHECK_EVERY_MS = 3000;

// What to tell the family member for each enrollment status.
const STATUS_MESSAGES = {
  pending: "We texted them. Waiting for them to reply YES…",
  active: "They said YES. Their calls are now protected. ✅",
  declined: "They said NO, so we won't listen to their calls.",
  expired: "They didn't answer within 24 hours. You can ask again.",
  revoked: "They turned Scam Shield off.",
};

// Remembered while the page is open.
let demoMode = false;
let seniorPhone = "";
let statusTimer = null;

/**
 * Ask the server if it's running, then show the answer on the page.
 *
 * Input:  nothing (it calls GET /health on our own server)
 * Output: nothing is returned; it updates the "Server status" text.
 * Example: server running in demo mode -> "Server status: online (demo mode)"
 */
async function showServerStatus() {
  const statusElement = document.getElementById("server-status");

  try {
    const response = await fetch("/health");
    const data = await response.json();
    demoMode = data.demo_mode;
    // Always say whether we're in demo mode, so nobody mistakes a
    // scripted demo call for a real one.
    const modeLabel = data.demo_mode ? "demo mode" : "live mode";
    statusElement.textContent = `online (${modeLabel})`;
    statusElement.classList.add("status-ok");
  } catch (error) {
    // If the server can't be reached, say so plainly instead of
    // leaving "checking…" on the screen forever.
    statusElement.textContent = "offline. Is the server running?";
  }
}

/**
 * Send a request with a JSON or form body and read the JSON answer.
 *
 * Input:  url, options — the same as fetch()
 * Output: {ok, data}: ok is true for a successful answer; data is the JSON
 *         (or {} if the answer had no JSON)
 * Example: await sendRequest("/api/demo/scam-call", {method: "POST"})
 *          -> {ok: true, data: {call_id: "...", join_link: "..."}}
 */
async function sendRequest(url, options) {
  const response = await fetch(url, options);
  let data = {};
  try {
    data = await response.json();
  } catch (error) {
    // Some answers (like Twilio-style XML) aren't JSON. That's fine.
  }
  return { ok: response.ok, data };
}

/**
 * Send the sign-up form. On success, switch to the "waiting for YES" panel.
 *
 * Input:  event — the form's submit event
 * Output: nothing; it updates the page.
 * Example: Ana fills in Rosa's details and taps the button
 *          -> Rosa gets a text; the page says "Waiting for Rosa"
 */
async function submitSignup(event) {
  // Stop the browser from reloading the page; we send the form ourselves.
  event.preventDefault();
  const form = event.target;
  const errorElement = document.getElementById("signup-error");
  errorElement.textContent = "";

  const fields = Object.fromEntries(new FormData(form));
  const { ok, data } = await sendRequest("/api/enrollments", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(fields),
  });

  if (!ok) {
    errorElement.textContent = data.error || "Something went wrong. Please try again.";
    return;
  }

  // Kept only so the demo button can pretend to be this phone.
  seniorPhone = fields.senior_phone;
  form.hidden = true;
  document.getElementById("consent-status").hidden = false;
  document.getElementById("senior-name").textContent = data.senior_name;
  document.getElementById("demo-tools").hidden = !demoMode;
  showConsentStatus(data.status);

  statusTimer = setInterval(() => checkConsent(data.id), CHECK_EVERY_MS);
}

/**
 * Ask the server whether the senior has answered yet.
 *
 * Input:  enrollmentId — the ID the server gave us at sign-up
 * Output: nothing; it updates the page, and stops checking once they answer.
 * Example: Rosa texts YES -> the page says "They said YES…"
 */
async function checkConsent(enrollmentId) {
  const { ok, data } = await sendRequest(`/api/enrollments/${enrollmentId}`);
  if (!ok) {
    return;
  }
  showConsentStatus(data.status);
  if (data.status !== "pending") {
    clearInterval(statusTimer);
  }
}

/**
 * Show the message for an enrollment status, and the right demo buttons.
 *
 * Example: showConsentStatus("active") -> "They said YES…" and the
 *          "Pretend a scam call starts" button appears (in demo mode)
 */
function showConsentStatus(status) {
  document.getElementById("consent-message").textContent = STATUS_MESSAGES[status] || status;
  document.getElementById("demo-reply-yes").hidden = status !== "pending";
  document.getElementById("demo-scam-call").hidden = status !== "active";
}

/**
 * Demo mode: pretend the senior texted YES, the way Twilio would tell us.
 *
 * Example: tap the button -> a few seconds later the page says "They said YES…"
 */
async function demoReplyYes() {
  await sendRequest("/twilio/sms", {
    method: "POST",
    body: new URLSearchParams({ From: seniorPhone, Body: "YES" }),
  });
  document.getElementById("demo-result").textContent = "Sent YES from their phone.";
}

/**
 * Demo mode: pretend a scam call started, which sends the family alert.
 * We show the "Join call" link from the alert so it can be opened right here.
 *
 * Example: tap the button -> "Family alert sent. Open the Join call link"
 */
async function demoScamCall() {
  const result = document.getElementById("demo-result");
  const { ok, data } = await sendRequest("/api/demo/scam-call", { method: "POST" });
  if (!ok) {
    result.textContent = data.error || "Couldn't start the demo call.";
    return;
  }
  result.textContent = "Family alert sent. ";
  const link = document.createElement("a");
  link.href = data.join_link;
  link.target = "_blank";
  link.textContent = "Open the Join call link";
  result.appendChild(link);
}

document.getElementById("signup-form").addEventListener("submit", submitSignup);
document.getElementById("demo-reply-yes").addEventListener("click", demoReplyYes);
document.getElementById("demo-scam-call").addEventListener("click", demoScamCall);
showServerStatus();
