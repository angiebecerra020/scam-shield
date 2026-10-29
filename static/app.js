/*
  app.js — Makes the dashboard page interactive.

  How it fits in: index.html loads this file after auth.js, busy.js and
  family.js. It:
    - checks the family member is logged in (or sends them to /login)
    - shows "Your family" (loadFamily() in family.js)
    - opens the sign-up form when the address ends in #protect, so a
      link can go straight to it
    - asks our server "are you running?" (GET /health) and shows the answer
    - sends the sign-up form (POST /api/enrollments), which texts the senior
      (cell phone) or calls them (landline)
    - checks every few seconds whether the senior said YES
      (GET /api/enrollments/{id})
    - once they do, shows the steps to finish setting up their phone
    - in demo mode, shows buttons that pretend to be the senior's phone
  Later it will show the live risk meter.

  The words come from strings.js, in English or Spanish (see i18n.js). When
  the language changes, we redraw the words this file put on the page.
*/

// How often to check whether the senior answered (milliseconds).
const CHECK_EVERY_MS = 3000;

// The statuses we have words for (as "status.pending" and so on, in strings.js).
const KNOWN_STATUSES = ["pending", "pendingCall", "active", "declined", "expired", "revoked"];

// Remembered while the page is open.
let demoMode = false;
// "checking", "online" or "offline", for the "Server status" line.
let serverState = "checking";
// The last sign-up we showed, so we can redraw it in a new language.
let lastEnrollment = null;
let seniorPhone = "";
let enrollmentId = "";
let phoneType = "cell";
// How we asked them for their YES. New sign-ups are always "call"; older
// ones may say "text".
let askBy = "call";
let statusTimer = null;

/**
 * Ask the server if it's running, then show the answer on the page.
 *
 * Input:  nothing (it calls GET /health on our own server)
 * Output: nothing is returned; it updates the "Server status" text.
 * Example: server running in demo mode -> "Server status: online (demo mode)"
 */
async function showServerStatus() {
  drawServerStatus();
  try {
    const response = await fetch("/health");
    const data = await response.json();
    demoMode = data.demo_mode;
    serverState = "online";
  } catch (error) {
    // If the server can't be reached, say so plainly instead of
    // leaving "checking…" on the screen forever.
    serverState = "offline";
  }
  drawServerStatus();
}

/**
 * Write the "Server status" line, in the current language.
 *
 * Example: online in demo mode  gives you  "online (demo mode)"
 */
function drawServerStatus() {
  const statusElement = document.getElementById("server-status");
  if (serverState === "checking") {
    statusElement.textContent = t("dash.checking");
  } else if (serverState === "offline") {
    statusElement.textContent = t("dash.offline");
  } else {
    // Always say whether we're in demo mode, so nobody mistakes a
    // scripted demo call for a real one.
    const mode = demoMode ? t("dash.demoMode") : t("dash.liveMode");
    statusElement.textContent = t("dash.online", { mode });
    statusElement.classList.add("status-ok");
  }
}

/**
 * Send a request with the login token, and read the JSON answer.
 * It never throws: if something goes wrong, data.error says what in plain
 * words (see fetchJson() in busy.js).
 *
 * Input:  url, options — the same as fetch()
 * Output: {ok, data}: ok is true for a successful answer; data is the JSON
 *         (or {} if the answer had no JSON, like Twilio-style XML)
 * Example: await sendRequest("/api/demo/scam-call", {method: "POST"})
 *          -> {ok: true, data: {call_id: "...", join_link: "..."}}
 */
async function sendRequest(url, options = {}) {
  let headers = { ...options.headers };
  try {
    // Add the login token, so the server knows who's asking (app/auth.py).
    headers = { ...headers, ...(await loginHeaders()) };
  } catch (error) {
    return { ok: false, data: { error: t("error.offline") } };
  }
  const { ok, status, data } = await fetchJson(url, { ...options, headers });
  if (status === 401) {
    // The login ran out (or they logged out in another tab). Back to /login.
    window.location.replace("/login");
  }
  return { ok, data };
}

/**
 * Send the sign-up form. On success, switch to the "waiting for YES" panel.
 *
 * Input:  event — the form's submit event
 * Output: nothing; it updates the page.
 * Example: Ana fills in Rosa's details and taps the button
 *          -> Rosa's phone rings; the page says "Waiting for Rosa"
 *          Ana types Rosa's phone as 555-0100 (no area code)
 *          -> a reminder to add the area code, and nothing is sent
 */
async function submitSignup(event) {
  // Stop the browser from reloading the page; we send the form ourselves.
  event.preventDefault();
  const form = event.target;
  const errorElement = document.getElementById("signup-error");
  errorElement.textContent = "";

  // A phone number without its area code can't be called, so remind them
  // and don't send anything until it's fixed. (The server checks too.)
  const short = findPhoneMissingAreaCode(form);
  if (short) {
    errorElement.textContent = t("dash.areaCodeMissing", { field: short.label });
    short.input.focus();
    return;
  }

  const fields = Object.fromEntries(new FormData(form));
  // Placing the call goes through Twilio, which can take a few seconds.
  // Say so, and stop a second tap from asking them twice.
  const button = form.querySelector('button[type="submit"]');
  setBusy(button, t("dash.busyCall"));
  const { ok, data } = await sendRequest("/api/enrollments", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(fields),
  });
  setReady(button);

  if (!ok) {
    errorElement.textContent = data.error;
    return;
  }

  // Kept only so the demo button can pretend to be this phone.
  seniorPhone = fields.senior_phone;
  enrollmentId = data.id;
  phoneType = data.phone_type;
  askBy = data.ask_by;
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
 * Find a phone number on the sign-up form that's missing its area code.
 *
 * A US number needs all 10 digits. A number starting with "+" is an
 * international one, so we leave it for the server to check.
 *
 * Input:  form — the sign-up form
 * Output: {input, label} for the first short number, or null if both are fine
 * Example: senior_phone "555-0100"  gives you  {input: <senior_phone>, label: "Their phone"}
 */
function findPhoneMissingAreaCode(form) {
  for (const input of [form.senior_phone, form.family_phone]) {
    const typed = input.value.trim();
    const digits = typed.replace(/\D/g, "");
    if (typed && !typed.startsWith("+") && digits.length < 10) {
      return { input, label: input.previousElementSibling.textContent };
    }
  }
  return null;
}

/**
 * Show notes on the sign-up form as they fill it in.
 *
 * Our phone voices can't speak Haitian Creole yet (see app/languages.py), so
 * picking Creole for the senior gets a note. And as soon as they leave a
 * phone box that's missing its area code, they get a reminder to add it.
 *
 * Input:  nothing (it reads the form)
 * Output: nothing; it updates the form.
 * Example: pick Kreyòl ayisyen  gives you  "We can't ask in Haitian Creole on our call yet..."
 *          type 555-0100 as their phone  gives you  "Their phone is missing the area code..."
 */
function checkSignupForm() {
  const form = document.getElementById("signup-form");
  document.getElementById("creole-call-note").hidden = form.senior_language.value !== "ht";

  const short = findPhoneMissingAreaCode(form);
  document.getElementById("signup-error").textContent = short
    ? t("dash.areaCodeMissing", { field: short.label })
    : "";
}

/**
 * Ask the server whether the senior has answered yet.
 *
 * Input:  enrollmentId — the ID the server gave us at sign-up
 * Output: nothing; it updates the page, and stops checking once they answer.
 * Example: Rosa texts YES -> the page says "They said YES…"
 */
async function checkConsent(enrollmentId) {
  const trouble = document.getElementById("consent-trouble");
  const { ok, data } = await sendRequest(`/api/enrollments/${enrollmentId}`);
  if (!ok) {
    // We keep checking, so say that instead of quietly freezing.
    trouble.textContent = t("dash.keepChecking", { problem: data.error });
    return;
  }
  trouble.textContent = "";
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
  lastEnrollment = enrollment;
  const status = enrollment.status;
  const messageKey = status === "pending" && askBy === "call" ? "pendingCall" : status;
  document.getElementById("consent-message").textContent = KNOWN_STATUSES.includes(messageKey)
    ? t(`status.${messageKey}`)
    : status;
  document.getElementById("demo-reply-yes").hidden = status !== "pending";
  document.getElementById("demo-scam-call").hidden = status !== "active";
  // "Call them again" only makes sense while we're still waiting on a call.
  document.getElementById("call-again").hidden = !(status === "pending" && askBy === "call");

  const setupSteps = document.getElementById("setup-steps");
  setupSteps.hidden = status !== "active";
  if (status === "active") {
    showSetupSteps(enrollment);
  }
}

/**
 * Add one numbered step to the setup list. The words come from strings.js,
 * and each {blank} is filled with plain text or a link.
 *
 * Input:  key — the step's words in strings.js
 *         blanks — what goes in each {blank}: text, or {link, label} for a link
 * Example: addStep("setup.cell2", {number: "+15555550150"})
 *          gives you  "Turn on call forwarding to +15555550150. On most phones..."
 */
function addStep(key, blanks) {
  const item = document.createElement("li");
  // Splitting on the blanks keeps their names: "open {appLink}, tap" gives
  // you ["open ", "appLink", ", tap"], with the names at the odd spots.
  // We read the raw words, not t(key), because t() fills unknown blanks with
  // nothing, and then the name, link and number would disappear.
  const words = STRINGS[currentLanguage][key] ?? STRINGS.en[key] ?? key;
  const pieces = words.split(/\{(\w+)\}/);
  pieces.forEach((piece, index) => {
    if (index % 2 === 0) {
      item.append(piece);
      return;
    }
    const value = blanks[piece];
    if (typeof value === "object") {
      const link = document.createElement("a");
      link.href = value.link;
      link.target = "_blank";
      link.textContent = value.label;
      item.appendChild(link);
    } else {
      item.append(value ?? "");
    }
  });
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
  const number = setup.forward_to || t("setup.yourNumber");
  document.getElementById("setup-list").replaceChildren();

  if (phoneType === "landline") {
    addStep("setup.landline1", {
      username: setup.adapter_username,
      domain: setup.adapter_domain || t("setup.yourDomain"),
    });
    addStep("setup.landline2", { name, number });
    addStep("setup.landline3", { name });
    document.getElementById("setup-note").textContent = t("setup.landlineOff");
  } else {
    addStep("setup.cell1", { name, appLink: { link: setup.app_link, label: t("setup.cellAppLink") } });
    addStep("setup.cell2", { name, number });
    document.getElementById("setup-note").textContent = t("setup.cellOff");
  }
}

/**
 * Rings the senior again with the "press 1 to say YES" call, in case they
 * missed it. The server limits how often (call_again.py).
 *
 * Example: tap "Call them again"  gives you  "We're calling them again now."
 */
async function callAgain() {
  const button = document.getElementById("call-again");
  const result = document.getElementById("call-again-result");
  setBusy(button, t("dash.busyCallAgain"));
  const answer = await sendRequest(`/api/enrollments/${enrollmentId}/call-again`, { method: "POST" });
  setReady(button);
  result.textContent = answer.ok ? t("dash.calledAgain") : answer.data.error;
}

/**
 * Demo mode: pretend the senior said YES, the way Twilio would tell us:
 * a YES text, or pressing 1 on the consent call, depending on how we asked.
 *
 * Example: tap the button -> a few seconds later the page says "They said YES…"
 */
async function demoReplyYes() {
  const button = document.getElementById("demo-reply-yes");
  const result = document.getElementById("demo-result");
  setBusy(button, t("dash.busyYes"));

  let answer;
  if (askBy === "call") {
    answer = await sendRequest(`/twilio/consent-answer?enrollment_id=${enrollmentId}`, {
      method: "POST",
      body: new URLSearchParams({ To: seniorPhone, Digits: "1" }),
    });
  } else {
    answer = await sendRequest("/twilio/sms", {
      method: "POST",
      body: new URLSearchParams({ From: seniorPhone, Body: "YES" }),
    });
  }
  setReady(button);

  if (!answer.ok) {
    result.textContent = answer.data.error;
    return;
  }
  result.textContent = askBy === "call" ? t("dash.demoPressed1") : t("dash.demoSentYes");
}

/**
 * Demo mode: pretend a scam call started, which sends the family alert.
 * We show the "Join call" link from the alert so it can be opened right here.
 *
 * Example: tap the button -> "Family alert sent. Open the Join call link"
 */
async function demoScamCall() {
  const button = document.getElementById("demo-scam-call");
  const result = document.getElementById("demo-result");
  setBusy(button, t("dash.busyScam"));
  const { ok, data } = await sendRequest("/api/demo/scam-call", { method: "POST" });
  setReady(button);
  if (!ok) {
    result.textContent = data.error;
    return;
  }
  result.textContent = `${t("dash.demoAlertSent")} `;
  const link = document.createElement("a");
  link.href = data.join_link;
  link.target = "_blank";
  link.textContent = t("dash.demoOpenJoin");
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
    document.body.textContent = t("error.refresh");
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
 * Open the sign-up form if the address ends in #protect, so a link can go
 * straight to it.
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
document.getElementById("signup-form").addEventListener("change", checkSignupForm);
// "Protect someone else" empties the form (family.js). The browser puts the
// old values back only after the "reset" event, so we check right after it.
document.getElementById("signup-form").addEventListener("reset", () => setTimeout(checkSignupForm));
document.getElementById("demo-reply-yes").addEventListener("click", demoReplyYes);
document.getElementById("call-again").addEventListener("click", callAgain);
document.getElementById("demo-scam-call").addEventListener("click", demoScamCall);
// When they flip the language switch, redraw the words this file made.
// (i18n.js already translated everything marked with data-text.)
document.addEventListener("language-switched", () => {
  drawServerStatus();
  if (lastEnrollment !== null) {
    showConsentStatus(lastEnrollment);
  }
});

// Following a #protect link while already on the dashboard only changes the
// #part of the address, which doesn't reload the page. So we watch for it.
window.addEventListener("hashchange", openSignupIfAsked);
startDashboard();
