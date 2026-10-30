/*
  phone.js — Makes the Scam Shield calling app (phone.html) ring and answer.

  How it fits in: phone.html loads this file after Twilio's calling library.
  It reads the secret key from the page address (/phone/<key>), gets a login
  from our server (GET /api/phone/<key>), and signs in to Twilio, so calls
  Scam Shield sends to this senior ring here. The login can only RECEIVE calls.

  A senior reads this screen, so when something goes wrong we say it in
  plain words and show the "Turn on calls" button again to retry.

  The words come from strings.js, in English or Spanish (see i18n.js).
*/

// The last part of the address, e.g. /phone/Xy7abc -> "Xy7abc"
const deviceKey = window.location.pathname.split("/").pop();

// Twilio's calling "device" and the call that's ringing or in progress.
let device = null;
let currentCall = null;

// The last status we showed, as a key and its blanks, so we can show it
// again in the other language when they flip the switch.
let lastStatus = { key: "phone.loading", details: {} };

/**
 * Show a status line at the top of the page, from strings.js.
 *
 * Example: showStatus("phone.whosePhone", {name: "Rosa"})  gives you  "Rosa's Scam Shield phone."
 */
function showStatus(key, details = {}) {
  lastStatus = { key, details };
  document.getElementById("phone-status").textContent = t(key, details);
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
 * Example: they tapped "Block" on the microphone question  gives you
 *          "Scam Shield needs the microphone to answer calls..."
 */
function friendlyProblem(error) {
  // The browser calls a blocked microphone "NotAllowedError", and a missing one "NotFoundError".
  if (error.name === "NotAllowedError" || error.name === "NotFoundError") {
    return t("phone.microphone");
  }
  // Our own messages (from fetchJson) are already in the reader's language.
  return error.message || t("phone.somethingWrong");
}

/**
 * Something stopped calls from ringing here. Say so, and bring back the
 * "Turn on calls" button so they can try again. During a call we only show
 * the message, so the Hang up button stays put.
 *
 * Input:  key, details — what to say, like showStatus()
 * Example: the internet drops  gives you  the message and the button
 */
function callsStopped(key, details = {}) {
  showStatus(key, details);
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
      showStatus("phone.whosePhoneDemo", { name: details.senior_name });
      return;
    }
    showStatus("phone.whosePhone", { name: details.senior_name });
    showOnly("turn-on");
  } catch (error) {
    showStatus("phone.problem", { problem: friendlyProblem(error) });
  }
}

/**
 * After the tap: ask for the microphone, sign in to Twilio, and wait for calls.
 *
 * Example: tap "Turn on calls" -> "Ready. Calls will ring here."
 */
async function turnOnCalls() {
  showOnly(null);
  showStatus("phone.turningOn");

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

    device.on("registered", () => showStatus("phone.ready"));
    device.on("error", () => {
      callsStopped("phone.stopped");
    });
    device.on("incoming", showIncomingCall);
    // The login lasts an hour; get a fresh one before it runs out.
    device.on("tokenWillExpire", async () => {
      try {
        const fresh = await loadDetails();
        device.updateToken(fresh.token);
      } catch (error) {
        callsStopped("phone.stopSoon", { problem: friendlyProblem(error) });
      }
    });

    showStatus("phone.connecting");
    await device.register();
  } catch (error) {
    showStatus("phone.couldntTurnOn", { problem: friendlyProblem(error) });
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
  const caller = call.parameters.From || t("phone.unknownNumber");
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
  showStatus("phone.ready");
}

document.getElementById("turn-on").addEventListener("click", turnOnCalls);
document.getElementById("answer").addEventListener("click", () => {
  currentCall.accept();
  showOnly("in-call");
});
document.getElementById("decline").addEventListener("click", () => currentCall.reject());
document.getElementById("hang-up").addEventListener("click", () => currentCall.disconnect());
// Show the last status again in the new language.
document.addEventListener("language-switched", () => showStatus(lastStatus.key, lastStatus.details));
start();
