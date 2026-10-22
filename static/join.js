/*
  join.js — Makes the "Join call" page work.

  How it fits in: join.html loads this file after busy.js. It reads the
  secret token from the page's address (/join/<token>), asks the server whose
  call it is (GET /api/join/<token>), and when the family member taps the
  button, asks the server to ring their phone into the call
  (POST /api/join/<token>).

  The family member opens this in a hurry, so the page always says what's
  happening: it never sits on "Checking the call…" forever, and the button
  can't ring their phone twice.
*/

// The last part of the address, e.g. /join/Xy7abc -> "Xy7abc"
const joinToken = window.location.pathname.split("/").pop();

/**
 * Show a message on the page.
 *
 * Example: showMessage("This call has already ended.")
 */
function showMessage(text) {
  document.getElementById("join-message").textContent = text;
}

/**
 * Say whether trying again could help. It can when the internet or our server
 * had trouble (status 0 or 500 and up), but not when the call has ended.
 *
 * Input:  status — the answer's status from fetchJson()
 * Output: true or false
 * Example: worthRetrying(0)  gives you  true (no internet)
 *          worthRetrying(410)  gives you  false (the call ended)
 */
function worthRetrying(status) {
  return status === 0 || status >= 500;
}

/**
 * Check the call is still going, then show the "Call me" button.
 *
 * Input:  nothing (uses joinToken)
 * Output: nothing; it updates the page.
 * Example: live call for Rosa -> "Rosa may be talking to a scammer right now."
 */
async function loadCall() {
  const { ok, status, data } = await fetchJson(`/api/join/${joinToken}`);

  if (!ok) {
    showMessage(data.error);
    document.getElementById("join-retry").hidden = !worthRetrying(status);
    return;
  }

  document.getElementById("join-retry").hidden = true;
  showMessage(`${data.senior_name} may be talking to a scammer right now.`);
  document.getElementById("join-button").hidden = false;
  document.getElementById("join-hint").hidden = false;
}

/**
 * Tap "Try again" after a connection problem: check the call again.
 *
 * Example: the Wi-Fi is back  gives you  "Rosa may be talking to a scammer right now."
 */
async function retryLoad() {
  const button = document.getElementById("join-retry");
  setBusy(button, "Checking…");
  showMessage("Checking the call…");
  await loadCall();
  setReady(button);
}

/**
 * Ask the server to ring the family member's phone into the call.
 *
 * Input:  nothing (uses joinToken)
 * Output: nothing; it updates the page.
 * Example: tap the button -> "Calling your phone now. Answer it to join Rosa's call."
 */
async function joinCall() {
  const button = document.getElementById("join-button");
  // Twilio takes a moment to ring their phone. Say so, and stop a double tap
  // from ringing them twice.
  setBusy(button, "Calling your phone…");

  const { ok, data } = await fetchJson(`/api/join/${joinToken}`, { method: "POST" });

  setReady(button);
  if (!ok) {
    showMessage(data.error);
    return;
  }

  showMessage(`Calling your phone now. Answer it to join ${data.senior_name}'s call.`);
  button.hidden = true;
}

document.getElementById("join-button").addEventListener("click", joinCall);
document.getElementById("join-retry").addEventListener("click", retryLoad);
loadCall();
