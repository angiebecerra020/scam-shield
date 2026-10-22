/*
  app.js — Makes the dashboard page interactive.

  How it fits in: index.html loads this file after auth.js and family.js. It:
    - checks the family member is logged in (or sends them to /login)
    - shows "Your family" (loadFamily() in family.js)
    - opens the sign-up form when the address ends in #protect (the
      header's "Protect someone" link, see nav.js)
    - asks our server "are you running?" (GET /health) and shows the answer
    - sends the sign-up form (POST /api/enrollments), which texts the senior
      (cell phone) or calls them (landline)
    - checks every few seconds whether the senior said YES
      (GET /api/enrollments/{id})
    - once they do, shows the steps to finish setting up their phone
    - in demo mode, shows buttons that pretend to be the senior's phone
  Later it will show the live risk meter.
*/

// How often to check whether the senior answered (milliseconds).
const CHECK_EVERY_MS = 3000;

// What to tell the family member for each enrollment status.
const STATUS_MESSAGES = {
  pending: "We texted them. Waiting for them to reply YES…",
  pendingLandline: "We're calling them now. Waiting for them to press 1…",
  active: "They said YES. Their calls are now protected. ✅",
  declined: "They said NO, so we won't listen to their calls.",
  expired: "They didn't answer within 24 hours. You can ask again.",
  revoked: "They turned Scam Shield off.",
};

// Remembered while the page is open.
let demoMode = false;
let seniorPhone = "";
let enrollmentId = "";
let phoneType = "cell";
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
async function sendRequest(url, options = {}) {
  // Add the login token, so the server knows who's asking (app/auth.py).
  const headers = { ...options.headers, ...(await loginHeaders()) };
  const response = await fetch(url, { ...options, headers });
  if (response.status === 401) {
    // The login ran out (or they logged out in another tab). Back to /login.
    window.location.replace("/login");
  }
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
  enrollmentId = data.id;
  phoneType = data.phone_type;
  form.hidden = true;
  document.getElementById("consent-status").hidden = false;
  document.getElementById("senior-name").textContent = data.senior_name;
  document.getElementById("demo-tools").hidden = !demoMode;
  showConsentStatus(data);
  // Add them to "Your family" right away, as "Waiting for their YES".
  loadFamily();

  // If they signed someone else up earlier, stop checking on that one.
  clearInterval(statusTimer);
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
  showConsentStatus(data);
  if (data.status !== "pending") {
    clearInterval(statusTimer);
    // They answered, so update their badge in "Your family".
    loadFamily();
  }
}

/**
 * Show the message for an enrollment's status, the setup steps once they
 * said YES, and the right demo buttons.
 *
 * Input:  enrollment — what the server sent, e.g. {status: "active", setup: {...}}
 * Example: status "active" -> "They said YES…", the setup steps, and the
 *          "Pretend a scam call starts" button (in demo mode)
 */
function showConsentStatus(enrollment) {
  const status = enrollment.status;
  const messageKey = status === "pending" && phoneType === "landline" ? "pendingLandline" : status;
  document.getElementById("consent-message").textContent = STATUS_MESSAGES[messageKey] || status;
  document.getElementById("demo-reply-yes").hidden = status !== "pending";
  document.getElementById("demo-scam-call").hidden = status !== "active";

  const setupSteps = document.getElementById("setup-steps");
  setupSteps.hidden = status !== "active";
  if (status === "active") {
    showSetupSteps(enrollment);
  }
}

/**
 * Add one numbered step to the setup list. Parts can be plain text or a link.
 *
 * Input:  parts — e.g. ["Open ", {link: "https://..."}, " on their phone."]
 * Example: addStep(["Dial *72 then ", "+15555550150"])
 */
function addStep(parts) {
  const item = document.createElement("li");
  for (const part of parts) {
    if (typeof part === "string") {
      item.append(part);
    } else {
      const link = document.createElement("a");
      link.href = part.link;
      link.target = "_blank";
      link.textContent = part.label || part.link;
      item.appendChild(link);
    }
  }
  document.getElementById("setup-list").appendChild(item);
}

/**
 * Show the steps to finish setup, which depend on the kind of phone.
 *
 * Every senior's number forwards to the Scam Shield number. Then Scam Shield
 * rings a calling app (cell phone) or a phone adapter (landline), never their
 * number itself, which would just forward back to us.
 *
 * Example: a landline -> "1. Set up the adapter... 2. Dial *72... 3. Plug in..."
 */
function showSetupSteps(enrollment) {
  const setup = enrollment.setup;
  const name = enrollment.senior_name;
  const forwardTo = setup.forward_to || "(your Scam Shield number)";
  document.getElementById("setup-list").replaceChildren();

  if (phoneType === "landline") {
    addStep([
      "Connect the phone adapter to their internet router and sign it in with username ",
      setup.adapter_username, " at ", setup.adapter_domain || "(your SIP domain)", ".",
    ]);
    addStep([
      `While ${name}'s phone is still plugged into the wall, pick it up and dial *72 then `,
      forwardTo, ". Wait for the tone, then hang up.",
    ]);
    addStep([`Unplug ${name}'s phone from the wall and plug it into the adapter.`]);
    document.getElementById("setup-note").textContent =
      "To turn Scam Shield off later: plug the phone back into the wall and dial *73.";
  } else {
    addStep([
      `On ${name}'s phone, open `, { link: setup.app_link, label: "this calling app link" },
      ", tap “Turn on calls”, and add it to the home screen.",
    ]);
    addStep([
      "Turn on call forwarding to ", forwardTo,
      ". On most phones, dial **21* then the number then #. On Verizon, dial *72 then the number.",
    ]);
    document.getElementById("setup-note").textContent =
      "To turn Scam Shield off later: dial ##21# (Verizon: *73), or text STOP to the Scam Shield number.";
  }
}

/**
 * Demo mode: pretend the senior said YES, the way Twilio would tell us:
 * a YES text for a cell phone, or pressing 1 on the consent call for a landline.
 *
 * Example: tap the button -> a few seconds later the page says "They said YES…"
 */
async function demoReplyYes() {
  if (phoneType === "landline") {
    await sendRequest(`/twilio/consent-answer?enrollment_id=${enrollmentId}`, {
      method: "POST",
      body: new URLSearchParams({ To: seniorPhone, Digits: "1" }),
    });
    document.getElementById("demo-result").textContent = "Pressed 1 on the consent call.";
    return;
  }
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

/**
 * Check the login, then show the dashboard.
 *
 * Input:  nothing
 * Output: nothing; it shows the page, or auth.js sends them to /login.
 * Example: Ana is logged in  gives you  the dashboard with "Logged in as ana@example.com"
 */
async function startDashboard() {
  let login;
  try {
    login = await requireLogin();
  } catch (error) {
    // We couldn't even ask the server about logins. Say so instead of
    // leaving a blank page.
    document.body.textContent = "We couldn't reach the server. Please refresh the page.";
    return;
  }
  if (login.loginOn && login.user === null) {
    return; // requireLogin() is already taking them to /login
  }
  if (login.user !== null) {
    document.getElementById("account-email").textContent = login.user.email;
    document.getElementById("account-bar").hidden = false;
  }
  document.getElementById("dashboard").hidden = false;
  showServerStatus();
  loadFamily();
  openSignupIfAsked();
}

/**
 * Open the sign-up form if the address ends in #protect. That's where the
 * header's "Protect someone" link goes (see nav.js).
 *
 * Input:  nothing (it reads the address)
 * Output: nothing; it opens the form, or does nothing.
 * Example: open /dashboard#protect  gives you  the dashboard with the empty sign-up form
 */
function openSignupIfAsked() {
  if (window.location.hash === "#protect") {
    showSignupForm();
  }
}

document.getElementById("signup-form").addEventListener("submit", submitSignup);
document.getElementById("demo-reply-yes").addEventListener("click", demoReplyYes);
document.getElementById("demo-scam-call").addEventListener("click", demoScamCall);
// Tapping "Protect someone" while already on the dashboard only changes the
// #part of the address, which doesn't reload the page. So we watch for it.
window.addEventListener("hashchange", openSignupIfAsked);
startDashboard();
