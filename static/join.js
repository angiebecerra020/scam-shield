/*
  join.js — Makes the "Join call" page work.

  How it fits in: join.html loads this file. It reads the secret token from
  the page's address (/join/<token>), asks the server whose call it is
  (GET /api/join/<token>), and when the family member taps the button, asks
  the server to ring their phone into the call (POST /api/join/<token>).
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
 * Check the call is still going, then show the "Call me" button.
 *
 * Input:  nothing (uses joinToken)
 * Output: nothing; it updates the page.
 * Example: live call for Rosa -> "Rosa may be talking to a scammer right now."
 */
async function loadCall() {
  const response = await fetch(`/api/join/${joinToken}`);
  const data = await response.json();

  if (!response.ok) {
    showMessage(data.error || "This call can't be joined.");
    return;
  }

  showMessage(`${data.senior_name} may be talking to a scammer right now.`);
  document.getElementById("join-button").hidden = false;
  document.getElementById("join-hint").hidden = false;
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
  // Stop double taps from ringing twice while we wait for the server.
  button.disabled = true;

  const response = await fetch(`/api/join/${joinToken}`, { method: "POST" });
  const data = await response.json();

  if (!response.ok) {
    showMessage(data.error || "We couldn't connect you. Please try again.");
    button.disabled = false;
    return;
  }

  showMessage(`Calling your phone now. Answer it to join ${data.senior_name}'s call.`);
  button.hidden = true;
}

document.getElementById("join-button").addEventListener("click", joinCall);
loadCall();
