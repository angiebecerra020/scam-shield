/*
  try.js

  This makes the "Call it yourself" page work. You get a code, call our
  number, and this page shows your call as Scam Shield hears it.

  How it fits in: try.html loads this file. It talks to the phone line in
  app/phone_line.py:
    POST /api/line/start              gets a code (and maybe an email for Ana's alert)
    GET  /api/line/{ticket}           everything on the call so far, asked every second
    POST /api/line/{ticket}/answer    Danny's YES or NO

  Everything the AI or the caller says gets put on the page as plain text,
  never as HTML, so a weird answer can never break the page.
*/

// How often we ask the server what's new on the call (milliseconds).
const CHECK_EVERY_MS = 1000;

// The words we show for each verdict.
const VERDICT_WORDS = {
  safe: "Looks safe",
  suspicious: "Suspicious",
  likely_scam: "Likely a scam",
  unknown: "Couldn't check this part",
};

// Nicer names for the Nemotron models, for the line under the score.
const MODEL_NAMES = {
  "nvidia/Nemotron-3_5-Lightning": "NVIDIA Nemotron 3.5 Lightning",
  "nvidia/Nemotron-3-Ultra-550b-a55b": "NVIDIA Nemotron 3 Ultra",
  "nvidia/nemotron-3-super-120b-a12b": "NVIDIA Nemotron 3 Super",
};

// Websites we label as official when Tavily finds them.
const OFFICIAL_SITES = ["aarp.org", "bbb.org"];

// What we say about the email to Ana, for each way it can go.
const EMAIL_NOTES = {
  sent: "We also emailed this alert to you.",
  failed: "We couldn't send the email this time.",
  not_set_up: "Email alerts aren't turned on yet.",
  limit: "We've sent a lot of emails today, so we skipped this one.",
  bad_address: "That email address didn't work.",
};

// Everything we remember while the page is open.
const state = {
  ticketId: null,
  timer: null,
  linesShown: 0,     // how many sentences are on Rosa's phone
  scoredLine: 0,     // the last sentence count we showed a score for
  familyShown: 0,    // how many of Ana's texts are on her phone
  contactShown: 0,   // how many of Danny's texts are on his phone
  warningsShown: 0,
  askedDanny: false,
  answeredDanny: false,
};

/**
 * Finds an element on the page by its id. Just a shortcut.
 *
 * Example: byId("score") gives you the big score number
 */
function byId(id) {
  return document.getElementById(id);
}

/**
 * Talks to our server and reads the answer.
 *
 * Input:  url, and body if we're sending something (that makes it a POST)
 * Output: {ok, status, data}. ok is true when it worked, data is the answer (or an error message)
 * Example: await api("/api/line/abc") gives you {ok: true, status: 200, data: {status: "live", ...}}
 */
async function api(url, body) {
  const options = {};
  if (body !== undefined) {
    options.method = "POST";
    options.headers = { "Content-Type": "application/json" };
    options.body = JSON.stringify(body);
  }

  try {
    const response = await fetch(url, options);
    let data = {};
    try {
      data = await response.json();
    } catch (problem) {
      // Some answers have no JSON in them. That's fine.
    }
    return { ok: response.ok, status: response.status, data };
  } catch (problem) {
    return { ok: false, status: 0, data: { error: "We couldn't reach the server. Check your connection and try again." } };
  }
}

/**
 * Shows an error under the form, or clears it when you pass nothing.
 *
 * Example: showError("That email doesn't look right.")
 */
function showError(text) {
  byId("line-error").textContent = text || "";
}

/**
 * Draws the Lucide icons.
 *
 * Example: drawIcons() turns every <i data-lucide="..."> into a picture
 */
function drawIcons() {
  if (window.lucide) {
    window.lucide.createIcons();
  }
}

/**
 * Writes a phone number the friendly way.
 *
 * Example: formatPhone("+13055550142") gives you "(305) 555-0142"
 */
function formatPhone(phone) {
  const digits = (phone || "").replace(/\D/g, "").slice(-10);
  if (digits.length !== 10) {
    return phone || "";
  }
  return `(${digits.slice(0, 3)}) ${digits.slice(3, 6)}-${digits.slice(6)}`;
}

/**
 * Puts a gray "nothing here yet" line in a list.
 *
 * Example: showEmpty("family-texts", "No alerts yet")
 */
function showEmpty(listId, text) {
  const item = document.createElement("li");
  item.className = "empty";
  item.textContent = text;
  byId(listId).replaceChildren(item);
}

/**
 * Clears everything from the last call, so a new code starts fresh.
 *
 * Example: getting a second code calls this
 */
function resetScreen() {
  showError("");
  setCallStatus("Waiting", false);
  byId("transcript").replaceChildren();
  byId("senior-warning").hidden = true;

  byId("ai").dataset.verdict = "waiting";
  byId("score").textContent = "0";
  byId("meter-fill").style.width = "0%";
  byId("verdict").textContent = "Start talking to see the score";
  byId("trail").replaceChildren();
  byId("thinking").hidden = true;
  byId("claimed").textContent = "Nobody yet";
  showEmpty("reasons", "Nothing worrying yet");
  byId("research-note").textContent = "Once the call seems suspicious, Tavily looks for matching scam warnings.";
  byId("sources").replaceChildren();
  byId("model-line").textContent = "";

  showEmpty("family-texts", "No alerts yet");
  showEmpty("contact-texts", "No texts yet");
  byId("email-note").hidden = true;
  byId("verify-buttons").hidden = true;

  state.linesShown = 0;
  state.scoredLine = 0;
  state.familyShown = 0;
  state.contactShown = 0;
  state.warningsShown = 0;
  state.askedDanny = false;
  state.answeredDanny = false;
}

/**
 * Updates the little status at the top of Rosa's phone.
 *
 * Example: setCallStatus("On the call", true) shows it in gold
 */
function setCallStatus(text, live) {
  const status = byId("call-status");
  status.textContent = text;
  status.classList.toggle("live", live);
}

/**
 * Writes seconds as minutes and seconds.
 *
 * Example: clock(272) gives you "4:32"
 */
function clock(seconds) {
  const minutes = Math.floor(seconds / 60);
  const rest = String(seconds % 60).padStart(2, "0");
  return `${minutes}:${rest}`;
}

/**
 * Shows where the call is at: waiting for you to call, on the call, or over.
 *
 * Example: showStatus({status: "live", seconds_left: 272}) says "On the call, 4:32 left"
 */
function showStatus(view) {
  const line = byId("line-status");
  line.classList.toggle("live", view.status === "live");

  if (view.status === "waiting") {
    line.textContent = "Waiting for your call";
    setCallStatus("Waiting", false);
  } else if (view.status === "live") {
    line.textContent = `On the call, ${clock(view.seconds_left || 0)} left`;
    setCallStatus("On the call", true);
  } else if (view.status === "ended") {
    line.textContent = "The call ended. Get a new code to try again.";
    setCallStatus("Call ended", false);
  } else {
    line.textContent = "This code ran out. Get a new one to try again.";
    setCallStatus("Waiting", false);
  }
}

/**
 * Adds one sentence the caller said to Rosa's phone.
 *
 * Example: addLine({speaker: "caller", text: "Grandma? It's me, Danny."})
 */
function addLine(line) {
  const item = document.createElement("li");
  item.className = "caller";

  const who = document.createElement("span");
  who.className = "who";
  who.textContent = "You";

  const words = document.createElement("span");
  words.textContent = line.text;

  item.append(who, words);
  const transcript = byId("transcript");
  transcript.appendChild(item);
  transcript.scrollTop = transcript.scrollHeight;
}

/**
 * Shows what Nemotron said: the score, the verdict, who they claim to be, and why.
 *
 * Example: a score of 92 turns the number and the meter red and says "Likely a scam"
 */
function showResult(latest) {
  const result = latest.result;
  const score = result.risk_score;

  byId("ai").dataset.verdict = result.verdict;
  byId("score").textContent = score === null ? "?" : String(score);
  byId("meter-fill").style.width = `${score === null ? 0 : score}%`;
  byId("verdict").textContent = VERDICT_WORDS[result.verdict] || result.verdict;
  byId("claimed").textContent = result.claimed_identity || "Nobody yet";

  if (result.reasons.length === 0) {
    showEmpty("reasons", "Nothing worrying yet");
  } else {
    const reasons = byId("reasons");
    reasons.replaceChildren();
    for (const reason of result.reasons) {
      const item = document.createElement("li");
      item.textContent = reason;
      reasons.appendChild(item);
    }
  }

  addToTrail(latest.line, score, result.verdict);

  const model = MODEL_NAMES[latest.model] || latest.model;
  byId("model-line").textContent = `Checked by ${model} on Nebius Token Factory in ${latest.seconds.toFixed(1)} seconds`;
}

/**
 * Adds one little bar to the score trail, so you can see the score climb sentence by sentence.
 *
 * Example: addToTrail(3, 85, "likely_scam") adds a tall red bar
 */
function addToTrail(lineNumber, score, verdict) {
  const bar = document.createElement("li");
  bar.className = verdict;
  bar.style.height = `${Math.max(score || 0, 8)}%`;
  bar.title = `After sentence ${lineNumber}: ${score === null ? "couldn't check" : score}`;
  byId("trail").appendChild(bar);
}

/**
 * Checks if a link is from a site we call official (government sites, AARP, the BBB).
 *
 * Example: isOfficial("https://www.fcc.gov/...") gives you true
 */
function isOfficial(url) {
  try {
    const host = new URL(url).hostname;
    if (host.endsWith(".gov")) {
      return true;
    }
    return OFFICIAL_SITES.some((site) => host === site || host.endsWith(`.${site}`));
  } catch (problem) {
    return false;
  }
}

/**
 * Adds one Tavily source to the list: the website, an "Official source"
 * label when it's one we trust, and the title as a link.
 *
 * Example: addSource({title: "Grandparent Scams", url: "https://www.fcc.gov/..."})
 */
function addSource(source) {
  // Only real web links go on the page.
  if (!/^https?:\/\//i.test(source.url)) {
    return;
  }

  const item = document.createElement("li");
  const site = document.createElement("span");
  site.className = "site";
  site.textContent = new URL(source.url).hostname.replace(/^www\./, "");
  if (isOfficial(source.url)) {
    const official = document.createElement("span");
    official.className = "official";
    official.textContent = "Official source";
    site.appendChild(official);
  }

  const link = document.createElement("a");
  link.href = source.url;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  link.textContent = source.title || source.url;

  item.append(site, link);
  byId("sources").appendChild(item);
}

/**
 * Shows the scam warnings Tavily found. We skip the caller's number here,
 * since on this line it's a made up one.
 *
 * Example: for a fake grandson call, you see warnings from AARP, the FCC and the BBB
 */
function showResearch(research) {
  if (!research) {
    return;
  }
  const sources = research.news.sources;
  byId("research-note").textContent =
    sources.length > 0 ? "Here are warnings about this kind of scam:" : "We didn't find matching warnings this time.";
  byId("sources").replaceChildren();
  for (const source of sources) {
    addSource(source);
  }
}

/**
 * Adds one message to Ana's or Danny's phone. Web links are left out, since
 * the "Join call" link only works for real protected calls.
 *
 * Input:  listId, "family-texts" or "contact-texts"
 *         body, what the message says
 *         kind, "reply" for Danny's own answer
 * Example: addText("family-texts", "Scam Shield ALERT: Rosa may be on a scam call...")
 */
function addText(listId, body, kind) {
  const list = byId(listId);
  const empty = list.querySelector(".empty");
  if (empty) {
    empty.remove();
  }

  const item = document.createElement("li");
  if (kind) {
    item.className = kind;
  } else if (/ALERT|ALERTA/.test(body)) {
    item.className = "alert";
  }
  // Drop the link and the words that point to it, like "Tap to join the call: https://..."
  item.textContent = body
    .replace(/\s*[^.!?:]*:\s*https?:\/\/\S+/g, "")
    .replace(/\s*https?:\/\/\S+/g, "")
    .trim();
  list.appendChild(item);
}

/**
 * Shows any of Ana's and Danny's messages we haven't shown yet.
 *
 * Example: showTexts({family: ["Scam Shield ALERT: ..."], contact: []})
 */
function showTexts(texts) {
  for (const body of texts.family.slice(state.familyShown)) {
    addText("family-texts", body);
  }
  state.familyShown = texts.family.length;

  for (const body of texts.contact.slice(state.contactShown)) {
    addText("contact-texts", body);
  }
  state.contactShown = texts.contact.length;
}

/**
 * Shows how the email to Ana went, if they asked for one.
 *
 * Example: showEmail({asked: true, status: "sent"}) says "We also emailed this alert to you."
 */
function showEmail(email) {
  const note = byId("email-note");
  if (!email.asked || !email.status) {
    return;
  }
  note.textContent = EMAIL_NOTES[email.status] || "";
  note.hidden = false;
}

/**
 * Shows Danny's YES and NO buttons the first time we ask him "Is that really you?"
 *
 * Example: once the caller says they're Danny, the buttons show up on Danny's phone
 */
function showVerify(check) {
  if (!check || state.askedDanny || state.answeredDanny || check.answer !== null) {
    return;
  }
  state.askedDanny = true;
  byId("verify-buttons").hidden = false;
}

/**
 * Shows Grandma's warning on her phone. Scam Shield says it out loud on the
 * call, so the page stays quiet (otherwise your phone would hear it twice).
 *
 * Example: showWarning({text: "This call looks like a scam..."})
 */
function showWarning(view) {
  if (!view.senior_warning || view.warning_count <= state.warningsShown) {
    return;
  }
  state.warningsShown = view.warning_count;
  byId("senior-warning-text").textContent = view.senior_warning.text;
  byId("senior-warning").hidden = false;
}

/**
 * Puts everything new from the server on the page.
 *
 * Example: show(view) after each check adds new sentences, the score, and any alerts
 */
function show(view) {
  showStatus(view);

  for (const line of view.lines.slice(state.linesShown)) {
    addLine(line);
  }
  state.linesShown = view.lines.length;

  const reading = view.status === "live" && view.checked < view.lines.length;
  byId("thinking").hidden = !reading;
  byId("ai").setAttribute("aria-busy", reading ? "true" : "false");

  if (view.latest && view.latest.line > state.scoredLine) {
    state.scoredLine = view.latest.line;
    showResult(view.latest);
    showResearch(view.latest.research);
  }
  if (view.latest) {
    showVerify(view.latest.verify);
  }

  showTexts(view.texts);
  showEmail(view.email);
  showWarning(view);

  if (view.note) {
    showError(view.note);
  }
}

/**
 * Shows our number and the code, so the visitor can call.
 *
 * Example: showDialCard({phone_number: "+13055550150", code: "4821"})
 */
function showDialCard(view) {
  const number = byId("dial-number");
  number.textContent = formatPhone(view.phone_number);
  number.href = `tel:${view.phone_number}`;
  byId("dial-code").textContent = view.code;
  byId("dial-card").hidden = false;
}

/**
 * Asks the server what's new on the call, shows it, and stops asking once the call is over.
 *
 * Example: runs every second after you get a code
 */
async function checkForNews() {
  if (!state.ticketId) {
    return;
  }
  const { ok, status, data } = await api(`/api/line/${encodeURIComponent(state.ticketId)}`);
  if (!ok) {
    stopChecking();
    showError(status === 404 ? "This code is gone. Get a new one to try again." : data.error);
    byId("get-code").disabled = false;
    return;
  }
  show(data);
  if (data.status === "ended" || data.status === "expired") {
    stopChecking();
    byId("get-code").disabled = false;
  }
}

/**
 * Starts asking the server for news every second.
 *
 * Example: startChecking() right after we get a code
 */
function startChecking() {
  stopChecking();
  state.timer = setInterval(checkForNews, CHECK_EVERY_MS);
}

/**
 * Stops asking the server for news.
 *
 * Example: stopChecking() once the call ends
 */
function stopChecking() {
  if (state.timer) {
    clearInterval(state.timer);
    state.timer = null;
  }
}

/**
 * Remembers the ticket in the address bar, so a refresh (or the link in
 * Ana's email) comes back to the same call.
 *
 * Example: rememberTicket("abc") makes the address /try?ticket=abc
 */
function rememberTicket(ticketId) {
  const url = new URL(window.location.href);
  url.searchParams.set("ticket", ticketId);
  window.history.replaceState(null, "", url);
}

/**
 * Gets a new code from the server and starts watching for the call.
 *
 * Example: pressing "Get my code"
 */
async function getCode(event) {
  event.preventDefault();
  const button = byId("get-code");
  button.disabled = true;
  stopChecking();
  resetScreen();

  const { ok, data } = await api("/api/line/start", {
    language: byId("language").value,
    family_language: byId("family-language").value,
    email: byId("email").value.trim(),
  });
  if (!ok) {
    showError(data.error || "We couldn't get a code. Please try again.");
    button.disabled = false;
    return;
  }

  state.ticketId = data.ticket_id;
  rememberTicket(data.ticket_id);
  showDialCard(data);
  show(data);
  startChecking();
}

/**
 * Sends Danny's answer to the server, then shows what happens next.
 *
 * Example: tapping "No, it's not me" warns Rosa on the call
 */
async function answerAsDanny(answer) {
  if (!state.ticketId) {
    return;
  }
  const buttons = byId("verify-buttons");
  buttons.hidden = true;

  const { ok, data } = await api(`/api/line/${encodeURIComponent(state.ticketId)}/answer`, { answer });
  if (!ok) {
    showError(data.error || "We couldn't send Danny's answer.");
    buttons.hidden = false;
    return;
  }

  state.answeredDanny = true;
  addText("contact-texts", answer === "yes" ? "YES" : "NO", "reply");
  show(data);
}

/**
 * Picks up where we left off if the address has a ticket in it (after a
 * refresh, or from the link in Ana's email).
 *
 * Example: opening /try?ticket=abc shows that call
 */
async function resumeTicket() {
  const ticketId = new URL(window.location.href).searchParams.get("ticket");
  if (!ticketId) {
    return;
  }
  state.ticketId = ticketId;
  const { ok, data } = await api(`/api/line/${encodeURIComponent(ticketId)}`);
  if (!ok) {
    state.ticketId = null;
    showError("That call is gone. Get a new code to try again.");
    return;
  }
  showDialCard(data);
  show(data);
  if (data.status === "waiting" || data.status === "live") {
    byId("get-code").disabled = true;
    startChecking();
  }
}

byId("code-form").addEventListener("submit", getCode);
byId("verify-yes").addEventListener("click", () => answerAsDanny("yes"));
byId("verify-no").addEventListener("click", () => answerAsDanny("no"));

resetScreen();
drawIcons();
resumeTicket();
