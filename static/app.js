/*
  app.js — Makes the dashboard page interactive.

  How it fits in: index.html loads this file after auth.js, busy.js and
  family.js. It:
    - checks the family member is logged in (or sends them to /login)
    - shows "Your family" (loadFamily() in family.js)
    - skips the "Who gets the alerts?" boxes once the family member has a
      profile (GET /api/profile); the server fills those in (app/profile.py)
    - opens the sign-up form when the address ends in #protect, so a
      link can go straight to it
    - asks our server "are you running?" (GET /health) and shows the answer
    - sends the sign-up form (POST /api/enrollments), which texts the senior
      (cell phone) or calls them (landline)
    - checks every few seconds whether the senior said YES
      (GET /api/enrollments/{id})
    - once they do, links to the steps to finish setting up their phone
  Later it will show the live risk meter.

  The words come from strings.js, in English or Spanish (see i18n.js). When
  the language changes, we redraw the words this file put on the page.
*/

// How often to check whether the senior answered (milliseconds).
const CHECK_EVERY_MS = 3000;

// The statuses we have words for (as "status.pending" and so on, in strings.js).
const KNOWN_STATUSES = ["pending", "pendingCall", "active", "declined", "expired", "revoked"];

// Remembered while the page is open.
// "checking", "online" or "offline", for the "Server status" line.
let serverState = "checking";
// The last sign-up we showed, so we can redraw it in a new language.
let lastEnrollment = null;
let enrollmentId = "";
let phoneType = "cell";
// How we asked them for their YES. New sign-ups are always "call"; older
// ones may say "text".
let askBy = "call";
let statusTimer = null;
// The family member's saved details (GET /api/profile), or null before their first sign-up.
let myProfile = null;

/**
 * Ask the server if it's running, then show the answer on the page.
 *
 * Input:  nothing (it calls GET /health on our own server)
 * Output: nothing is returned; it updates the "Server status" text.
 * Example: server running -> "Server status: online"
 */
async function showServerStatus() {
  drawServerStatus();
  try {
    const response = await fetch("/health");
    if (!response.ok) {
      throw new Error(`The server answered ${response.status}`);
    }
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
 * Example: online  gives you  "online"
 */
function drawServerStatus() {
  const statusElement = document.getElementById("server-status");
  if (serverState === "checking") {
    statusElement.textContent = t("dash.checking");
  } else if (serverState === "offline") {
    statusElement.textContent = t("dash.offline");
  } else {
    statusElement.textContent = t("dash.online");
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
 * Example: await sendRequest("/api/family")
 *          -> {ok: true, data: {seniors: [...]}}
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
 * Ask the server for the family member's profile, and show or skip the
 * "Who gets the alerts?" boxes on the sign-up form.
 *
 * Input:  nothing (it calls GET /api/profile)
 * Output: nothing; it updates the form.
 * Example: Ana has a profile  gives you  "Alerts go to Ana · 305-555-0101"
 *          instead of the boxes
 */
async function loadProfile() {
  const { ok, data } = await sendRequest("/api/profile");
  // If we can't tell, keep the boxes: typing them again beats being stuck.
  myProfile = ok ? data.profile : null;
  drawFamilyFields();
}

/**
 * Show the "Alerts go to" note when there's a profile, or the boxes when there isn't.
 *
 * A disabled fieldset's boxes aren't required and aren't sent with the
 * form, so the server uses the profile instead.
 *
 * Example: myProfile {name: "Ana", phone: "+13055550101", email: "ana@example.com"}
 *          gives you "Alerts go to Ana · 305-555-0101 · ana@example.com"
 */
function drawFamilyFields() {
  const haveProfile = myProfile !== null;
  const fields = document.getElementById("family-fields");
  fields.hidden = haveProfile;
  fields.disabled = haveProfile;
  document.getElementById("alerts-go-to").hidden = !haveProfile;
  if (haveProfile) {
    const parts = [myProfile.name, showPhone(myProfile.phone)];
    if (myProfile.email) {
      parts.push(myProfile.email);
    }
    document.getElementById("alerts-go-to-who").textContent = parts.join(" · ");
  }
}

/**
 * Write a saved US number the way people type it.
 *
 * Example: showPhone("+13055550101")  gives you  "305-555-0101"
 */
function showPhone(phone) {
  const us = /^\+1(\d{3})(\d{3})(\d{4})$/.exec(phone);
  return us ? `${us[1]}-${us[2]}-${us[3]}` : phone;
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

  enrollmentId = data.id;
  phoneType = data.phone_type;
  askBy = data.ask_by;
  form.hidden = true;
  document.getElementById("consent-status").hidden = false;
  document.getElementById("senior-name").textContent = data.senior_name;
  showConsentStatus(data);
  // Add them to "Your family" right away, as "Waiting for their YES".
  loadFamily();
  // Their first sign-up saved their profile, so next time the form is shorter.
  if (myProfile === null) {
    loadProfile();
  }

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
    // A disabled box isn't sent (the profile fills it in), so skip it.
    if (input.matches(":disabled")) {
      continue;
    }
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
 * As soon as they leave a phone box that's missing its area code, they get
 * a reminder to add it.
 *
 * Input:  nothing (it reads the form)
 * Output: nothing; it updates the form.
 * Example: type 555-0100 as their phone  gives you  "Their phone is missing the area code..."
 */
function checkSignupForm() {
  const form = document.getElementById("signup-form");
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
 * Show the message for an enrollment's status, the link to the setup steps once they
 * said YES, and the "Call them again" button while we wait.
 *
 * Input:  enrollment — what the server sent, e.g. {status: "active", setup: {...}}
 * Example: status "active" -> "They said YES…" and the "Show me the steps" link
 */
function showConsentStatus(enrollment) {
  lastEnrollment = enrollment;
  const status = enrollment.status;
  const messageKey = status === "pending" && askBy === "call" ? "pendingCall" : status;
  document.getElementById("consent-message").textContent = KNOWN_STATUSES.includes(messageKey)
    ? t(`status.${messageKey}`)
    : status;
  // "Call them again" only makes sense while we're still waiting on a call.
  document.getElementById("call-again").hidden = !(status === "pending" && askBy === "call");

  const setupSteps = document.getElementById("setup-steps");
  setupSteps.hidden = status !== "active";
  // The steps themselves are on their own page (setup.html).
  document.getElementById("setup-link").href = `/setup/${enrollment.id}`;
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
  loadProfile();
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
document.getElementById("call-again").addEventListener("click", callAgain);
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
