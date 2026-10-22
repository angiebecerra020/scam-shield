/*
  phone.js — Makes the Scam Shield calling app (phone.html) ring and answer.

  How it fits in: phone.html loads this file after Twilio's calling library.
  It reads the secret key from the page address (/phone/<key>), gets a login
  from our server (GET /api/phone/<key>), and signs in to Twilio, so calls
  Scam Shield sends to this senior ring here. The login can only RECEIVE calls.

  A senior reads this screen, so when something goes wrong we say it in
  plain words and show the "Turn on calls" button again to retry.
*/

// What we say when the microphone is blocked. Calls can't be answered without it.
const MICROPHONE_MESSAGE =
  "Scam Shield needs the microphone to answer calls. Allow it for this page in your browser, then tap Turn on calls.";

// The last part of the address, e.g. /phone/Xy7abc -> "Xy7abc"
const deviceKey = window.location.pathname.split("/").pop();

// Twilio's calling "device" and the call that's ringing or in progress.
let device = null;
let currentCall = null;

/**
 * Show a status line at the top of the page.
 *
 * Example: showStatus("Ready for calls.")
 */
function showStatus(text) {
  document.getElementById("phone-status").textContent = text;
}

/**
 * Show only one part of the page: "turn-on", "incoming", "in-call", or none.
 *
 * Example: showOnly("incoming") -> the Answer / Decline buttons appear
 */
function showOnly(sectionId) {
  for (const id of ["turn-on", "incoming", "in-call"]) {
    document.getElementById(id).hidden = id !== sectionId;
  }
}

/**
 * Ask our server for this phone's details and Twilio login.
 *
 * Output: {senior_name, demo_mode, token}, or throws with the server's message
 * Example: await loadDetails() -> {senior_name: "Rosa", demo_mode: false, token: "eyJ..."}
 */
async function loadDetails() {
  // fetchJson (busy.js) never throws, and gives a plain message when the
  // internet or our server has trouble.
  const { ok, data } = await fetchJson(`/api/phone/${deviceKey}`);
  if (!ok) {
    throw new Error(data.error);
  }
  return data;
}

/**
 * Turn whatever went wrong into words a senior understands.
 *
 * Input:  error — what was thrown while turning on calls
 * Output: the message to show
 * Example: they tapped "Block" on the microphone question  gives you  MICROPHONE_MESSAGE
 */
function friendlyProblem(error) {
  // The browser calls a blocked microphone "NotAllowedError", and a missing one "NotFoundError".
  if (error.name === "NotAllowedError" || error.name === "NotFoundError") {
    return MICROPHONE_MESSAGE;
  }
  return error.message || "Something went wrong. Tap Turn on calls to try again.";
}

/**
 * Something stopped calls from ringing here. Say so, and bring back the
 * "Turn on calls" button so they can try again. During a call we only show
 * the message, so the Hang up button stays put.
 *
 * Input:  text — what to say
 * Example: the internet drops  gives you  the message and the button
 */
function callsStopped(text) {
  showStatus(text);
  if (currentCall === null) {
    showOnly("turn-on");
  }
}

/**
 * First load: check the link, then show the "Turn on calls" button.
 *
 * Example: a good link -> "Rosa's Scam Shield phone" + the button
 */
async function start() {
  try {
    const details = await loadDetails();
    if (details.demo_mode) {
      showStatus(`${details.senior_name}'s Scam Shield phone. Demo mode: real calls don't ring here.`);
      return;
    }
    showStatus(`${details.senior_name}'s Scam Shield phone.`);
    showOnly("turn-on");
  } catch (error) {
    showStatus(error.message);
  }
}

/**
 * After the tap: ask for the microphone, sign in to Twilio, and wait for calls.
 *
 * Example: tap "Turn on calls" -> "Ready. Calls will ring here."
 */
async function turnOnCalls() {
  showOnly(null);
  showStatus("Turning on…");

  try {
    // Ask for the microphone now, so answering a call later is one tap.
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    stream.getTracks().forEach((track) => track.stop());

    const details = await loadDetails();
    // If they're trying again, shut the old connection first, so calls
    // don't ring twice.
    if (device !== null) {
      device.destroy();
    }
    // closeProtection warns before the page is closed during a call.
    device = new Twilio.Device(details.token, { closeProtection: true });

    device.on("registered", () => showStatus("Ready. Calls will ring here."));
    device.on("error", () => {
      callsStopped("Calls stopped working here. Check the internet, then tap Turn on calls.");
    });
    device.on("incoming", showIncomingCall);
    // The login lasts an hour; get a fresh one before it runs out.
    device.on("tokenWillExpire", async () => {
      try {
        const fresh = await loadDetails();
        device.updateToken(fresh.token);
      } catch (error) {
        callsStopped(`Calls will stop ringing here soon. ${friendlyProblem(error)}`);
      }
    });

    showStatus("Connecting…");
    await device.register();
  } catch (error) {
    showStatus(`Couldn't turn on calls. ${friendlyProblem(error)}`);
    showOnly("turn-on");
  }
}

/**
 * A call is ringing: show who's calling and the Answer / Decline buttons.
 *
 * Input:  call — Twilio's call object
 * Example: a call from +13055550199 -> "Call from +13055550199"
 */
function showIncomingCall(call) {
  currentCall = call;
  const caller = call.parameters.From || "Unknown number";
  document.getElementById("caller-number").textContent = caller;
  document.getElementById("in-call-number").textContent = caller;
  showOnly("incoming");

  // However the call ends (they hang up, we decline, the caller gives up),
  // go back to waiting.
  for (const event of ["disconnect", "cancel", "reject"]) {
    call.on(event, callEnded);
  }
}

/**
 * Go back to "Ready" after a call ends.
 */
function callEnded() {
  currentCall = null;
  showOnly(null);
  showStatus("Ready. Calls will ring here.");
}

document.getElementById("turn-on").addEventListener("click", turnOnCalls);
document.getElementById("answer").addEventListener("click", () => {
  currentCall.accept();
  showOnly("in-call");
});
document.getElementById("decline").addEventListener("click", () => currentCall.reject());
document.getElementById("hang-up").addEventListener("click", () => currentCall.disconnect());
start();
