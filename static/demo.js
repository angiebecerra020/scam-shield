/*
  demo.js

  This makes the demo player work. You pick a call, press Play, and watch
  Scam Shield check it line by line.

  How it fits in: demo.html loads this file. It talks to the demo routes in
  app/demo_api.py:
    GET  /api/demo/calls                    the list of test calls
    POST /api/demo/calls/{id}/start         starts one (and makes up the family)
    POST /api/demo/live/{call_id}/check     checks the call after each line
    POST /api/demo/live/{call_id}/answer    Danny's YES or NO

  Everything the AI or a test call says gets put on the page as plain text,
  never as HTML, so a weird answer can never break the page.
*/

// How long we wait between lines while playing (milliseconds), so it feels like a real call.
const PAUSE_BETWEEN_LINES_MS = 900;

// How long the "someone is talking" dots show before each line.
const TYPING_MS = 650;

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

// Everything we remember while the page is open.
const state = {
  call: null,       // the demo call from the server, with all its lines
  nextLine: 0,      // which line comes next
  playing: false,   // true while Play is running
  busy: false,      // true while we're showing a line or waiting on the AI
  soundOn: true,    // spoken warnings for Rosa
  askedDanny: false,
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
 * Waits for some milliseconds. We use it to pace the call like a real one.
 *
 * Example: await wait(900) pauses for almost a second
 */
function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * Talks to our server and reads the answer.
 *
 * Input:  url, and body if we're sending something (that makes it a POST)
 * Output: {ok, data}. ok is true when it worked, data is the answer (or an error message)
 * Example: await api("/api/demo/calls") gives you {ok: true, data: [ ...20 calls ]}
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
    return { ok: response.ok, data };
  } catch (problem) {
    return { ok: false, data: { error: "We couldn't reach the server. Check your connection and try again." } };
  }
}

/**
 * Shows an error under the controls, or clears it when you pass nothing.
 *
 * Example: showError("We couldn't start the call.")
 */
function showError(text) {
  byId("demo-error").textContent = text || "";
}

/**
 * Draws the Lucide icons. We call it again whenever we add a new icon.
 *
 * Example: after swapping the sound icon, drawIcons() turns it into a picture
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
    return phone || "Unknown number";
  }
  return `(${digits.slice(0, 3)}) ${digits.slice(3, 6)}-${digits.slice(6)}`;
}

/**
 * Puts a gray "nothing here yet" line in a list.
 *
 * Example: showEmpty("family-texts", "No texts yet")
 */
function showEmpty(listId, text) {
  const item = document.createElement("li");
  item.className = "empty";
  item.textContent = text;
  byId(listId).replaceChildren(item);
}

/**
 * Loads our 20 test calls into the picker, with scams and normal calls in their own groups.
 *
 * Example: after this, the picker shows "Scam calls" and "Normal calls"
 */
async function loadCalls() {
  const { ok, data } = await api("/api/demo/calls");
  if (!ok) {
    showError(data.error || "We couldn't load the demo calls.");
    return;
  }

  const scams = document.createElement("optgroup");
  scams.label = "Scam calls";
  const normal = document.createElement("optgroup");
  normal.label = "Normal calls";

  for (const call of data) {
    const option = document.createElement("option");
    option.value = call.id;
    const language = call.language === "es" ? "Spanish" : "English";
    option.textContent = `${call.title} (${language})`;
    if (call.expected === "scam") {
      scams.appendChild(option);
    } else {
      normal.appendChild(option);
    }
  }

  const picker = byId("call-picker");
  picker.replaceChildren(scams, normal);
  picker.value = "scam_grandparent_en";
}

/**
 * Puts everything back to the way it looks before a call starts.
 *
 * Example: pressing Start over calls this
 */
function resetScreen() {
  showError("");
  byId("caller-number").textContent = "No call yet";
  setCallStatus("Waiting", false);
  byId("transcript").replaceChildren();
  byId("senior-warning").hidden = true;

  const ai = byId("ai");
  ai.dataset.verdict = "waiting";
  byId("score").textContent = "0";
  byId("meter-fill").style.width = "0%";
  byId("verdict").textContent = "Press Play to start the call";
  byId("trail").replaceChildren();
  byId("thinking").hidden = true;
  byId("claimed").textContent = "Nobody yet";
  showEmpty("reasons", "Nothing worrying yet");
  byId("research-note").textContent =
    "Once the call seems suspicious, Tavily checks the caller's number and looks for matching scam warnings.";
  byId("sources").replaceChildren();
  byId("model-line").textContent = "";

  showEmpty("family-texts", "No texts yet");
  showEmpty("contact-texts", "No texts yet");
  byId("verify-buttons").hidden = true;
  state.askedDanny = false;

  if ("speechSynthesis" in window) {
    window.speechSynthesis.cancel();
  }
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
 * Starts a new demo call on the server with the call and language you picked.
 *
 * Output: true if it started, false if something went wrong (the error shows on the page)
 * Example: pressing Play the first time calls this
 */
async function startCall() {
  resetScreen();
  const scriptId = byId("call-picker").value;
  const familyLanguage = byId("family-language").value;
  const { ok, data } = await api(`/api/demo/calls/${encodeURIComponent(scriptId)}/start`, {
    family_language: familyLanguage,
  });
  if (!ok) {
    showError(data.error || "We couldn't start the call.");
    return false;
  }

  state.call = data;
  state.nextLine = 0;
  byId("caller-number").textContent = formatPhone(data.caller_number);
  setCallStatus("On the call", true);
  return true;
}

/**
 * Shows the "someone is talking" dots for a moment before a line appears.
 *
 * Example: await showTyping("caller") shows the dots on the caller's side
 */
async function showTyping(speaker) {
  const dots = document.createElement("li");
  dots.className = `${speaker} typing`;
  dots.setAttribute("aria-hidden", "true");
  for (let i = 0; i < 3; i += 1) {
    dots.appendChild(document.createElement("span"));
  }
  const transcript = byId("transcript");
  transcript.appendChild(dots);
  transcript.scrollTop = transcript.scrollHeight;
  await wait(TYPING_MS);
  dots.remove();
}

/**
 * Adds one line of the call to Rosa's phone.
 *
 * Example: addLine({speaker: "caller", text: "Grandma? It's me, Danny."})
 */
function addLine(line) {
  const item = document.createElement("li");
  item.className = line.speaker;

  const who = document.createElement("span");
  who.className = "who";
  who.textContent = line.speaker === "caller" ? "Caller" : "Rosa";

  const words = document.createElement("span");
  words.textContent = line.text;

  item.append(who, words);
  const transcript = byId("transcript");
  transcript.appendChild(item);
  transcript.scrollTop = transcript.scrollHeight;
}

/**
 * Shows that the call is over.
 *
 * Example: after the last line, Rosa's phone says "The call ended"
 */
function endCall() {
  const item = document.createElement("li");
  item.className = "ended";
  item.textContent = "The call ended";
  byId("transcript").appendChild(item);
  setCallStatus("Call ended", false);
  state.playing = false;
}

/**
 * Turns the "Nemotron is reading the call" message on or off.
 *
 * Example: setThinking(true) while we wait for the AI
 */
function setThinking(on) {
  byId("thinking").hidden = !on;
  byId("ai").setAttribute("aria-busy", on ? "true" : "false");
}

/**
 * Shows what Nemotron said: the score, the verdict, who they claim to be, and why.
 *
 * Example: a score of 92 turns the number and the meter red and says "Likely a scam"
 */
function showResult(data) {
  const result = data.result;
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

  addToTrail(data.line, score, result.verdict);

  const model = MODEL_NAMES[data.model] || data.model;
  byId("model-line").textContent = `Checked by ${model} on Nebius Token Factory in ${data.seconds.toFixed(1)} seconds`;
}

/**
 * Adds one little bar to the score trail, so you can see the score climb line by line.
 *
 * Example: addToTrail(3, 85, "likely_scam") adds a tall red bar
 */
function addToTrail(lineNumber, score, verdict) {
  const bar = document.createElement("li");
  bar.className = verdict;
  bar.style.height = `${Math.max(score || 0, 8)}%`;
  bar.title = `After line ${lineNumber}: ${score === null ? "couldn't check" : score}`;
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
 * Adds one Tavily source to the list: the website, a "Official source" label
 * when it's one we trust, and the title as a link.
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
 * Shows what Tavily found about the caller's number and matching scam warnings.
 *
 * Example: for the fake grandson call, you see warnings from AARP, the FCC and the BBB
 */
function showResearch(research) {
  if (!research) {
    return;
  }

  const caller = research.caller;
  const notes = [];
  if (caller.reported_as_scam) {
    notes.push("This number shows up in scam reports.");
  } else {
    notes.push("We didn't find scam reports about this number.");
  }
  if (research.news.sources.length > 0) {
    notes.push("Here are warnings about this kind of scam:");
  }
  byId("research-note").textContent = notes.join(" ");

  byId("sources").replaceChildren();
  for (const source of caller.sources.concat(research.news.sources)) {
    addSource(source);
  }
}

/**
 * Adds one text message to Ana's or Danny's phone. Links become a tappable
 * "Join the call" link instead of a long web address.
 *
 * Input:  listId, "family-texts" or "contact-texts"
 *         body, what the text says
 *         kind, "reply" for Danny's own answer
 * Example: addText("family-texts", "Scam Shield ALERT: ... http://.../join/abc")
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

  const parts = body.split(/(https?:\/\/\S+)/);
  for (const part of parts) {
    if (/^https?:\/\//.test(part)) {
      const link = document.createElement("a");
      link.href = part;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = "Join the call";
      item.appendChild(link);
    } else if (part) {
      item.appendChild(document.createTextNode(part));
    }
  }
  list.appendChild(item);
}

/**
 * Shows any new texts for Ana and Danny.
 *
 * Example: showTexts({family: ["Scam Shield ALERT: ..."], contact: []})
 */
function showTexts(texts) {
  if (!texts) {
    return;
  }
  for (const body of texts.family) {
    addText("family-texts", body);
  }
  for (const body of texts.contact) {
    addText("contact-texts", body);
  }
}

/**
 * Shows Danny's YES and NO buttons the first time we ask him "Is that really you?"
 *
 * Example: after the fake Danny says he's in jail, the buttons show up on Danny's phone
 */
function showVerify(check) {
  if (!check || state.askedDanny || check.answer !== null) {
    return;
  }
  state.askedDanny = true;
  byId("verify-buttons").hidden = false;
}

/**
 * Sends Danny's answer to the server, then shows what happens next.
 *
 * Example: tapping "No, it's not me" warns Rosa and texts Ana
 */
async function answerAsDanny(answer) {
  if (!state.call) {
    return;
  }
  const buttons = byId("verify-buttons");
  buttons.hidden = true;

  const { ok, data } = await api(`/api/demo/live/${state.call.call_id}/answer`, { answer });
  if (!ok) {
    showError(data.error || "We couldn't send Danny's answer.");
    buttons.hidden = false;
    return;
  }

  addText("contact-texts", answer === "yes" ? "YES" : "NO", "reply");
  showTexts(data.texts);
  showWarning(data.senior_warning);
}

/**
 * Shows Rosa's warning on her phone, and reads it out loud in her language.
 *
 * Example: showWarning({text: "This call looks like a scam...", speech_language: "en-US"})
 */
function showWarning(warning) {
  if (!warning) {
    return;
  }
  byId("senior-warning-text").textContent = warning.text;
  byId("senior-warning").hidden = false;
  speak(warning.text, warning.speech_language);
}

/**
 * Reads some text out loud with the browser's own voice, if sound is on.
 *
 * Example: speak("Cuelgue ahora.", "es-US") says it in Spanish
 */
function speak(text, language) {
  if (!state.soundOn || !("speechSynthesis" in window)) {
    return;
  }
  window.speechSynthesis.cancel();
  const words = new SpeechSynthesisUtterance(text);
  words.lang = language;
  // A little slower than normal, so it's easier to understand.
  words.rate = 0.92;
  window.speechSynthesis.speak(words);
}

/**
 * Turns the spoken warnings on or off.
 *
 * Example: tapping the speaker button when it's on turns the voice off
 */
function toggleSound() {
  state.soundOn = !state.soundOn;
  const button = byId("sound");
  button.setAttribute("aria-pressed", state.soundOn ? "true" : "false");
  button.setAttribute(
    "aria-label",
    state.soundOn ? "Spoken warnings are on. Turn them off." : "Spoken warnings are off. Turn them on."
  );
  const icon = document.createElement("i");
  icon.dataset.lucide = state.soundOn ? "volume-2" : "volume-x";
  icon.setAttribute("aria-hidden", "true");
  button.replaceChildren(icon);
  drawIcons();
  if (!state.soundOn && "speechSynthesis" in window) {
    window.speechSynthesis.cancel();
  }
}

/**
 * Asks the server to check the call so far, then shows everything it found.
 *
 * Example: after line 3 of the fake grandson call, the score jumps and Ana gets the alert
 */
async function runCheck(lineNumber) {
  setThinking(true);
  const { ok, data } = await api(`/api/demo/live/${state.call.call_id}/check`, { up_to_line: lineNumber });
  setThinking(false);

  if (!ok) {
    showError(data.error || "We couldn't check that line.");
    state.playing = false;
    return;
  }
  showResult(data);
  showResearch(data.research);
  showTexts(data.texts);
  showVerify(data.verify);
  showWarning(data.senior_warning);
}

/**
 * Plays the next line of the call. If the caller said it, we check the call
 * with the AI right after (the senior's lines don't change the risk much,
 * and this saves credits).
 *
 * Output: true if there are more lines to go
 * Example: pressing Next line calls this once
 */
async function step() {
  if (state.busy) {
    return false;
  }
  state.busy = true;
  updateButtons();

  try {
    if (!state.call || state.nextLine >= state.call.lines.length) {
      const started = await startCall();
      if (!started) {
        return false;
      }
    }

    const line = state.call.lines[state.nextLine];
    await showTyping(line.speaker);
    addLine(line);
    state.nextLine += 1;

    if (line.speaker === "caller") {
      await runCheck(state.nextLine);
    }

    const more = state.nextLine < state.call.lines.length;
    if (!more) {
      endCall();
    }
    return more;
  } finally {
    state.busy = false;
    updateButtons();
  }
}

/**
 * Plays the whole call, one line at a time. Press it again to pause.
 *
 * Example: pressing Play runs the fake grandson call from start to finish
 */
async function play() {
  if (state.playing) {
    state.playing = false;
    updateButtons();
    return;
  }

  state.playing = true;
  updateButtons();
  while (state.playing) {
    const more = await step();
    if (!more) {
      break;
    }
    await wait(PAUSE_BETWEEN_LINES_MS);
  }
  state.playing = false;
  updateButtons();
}

/**
 * Stops everything and clears the screen, ready for a new call.
 *
 * Example: changing the call in the picker calls this
 */
function startOver() {
  state.playing = false;
  state.call = null;
  state.nextLine = 0;
  resetScreen();
  updateButtons();
}

/**
 * Updates the buttons so they always match what's happening.
 *
 * Example: while playing, the Play button says Pause and Next line is turned off
 */
function updateButtons() {
  byId("play").querySelector("span").textContent = state.playing ? "Pause" : "Play";
  byId("step").disabled = state.playing || state.busy;
}

byId("play").addEventListener("click", play);
byId("step").addEventListener("click", step);
byId("restart").addEventListener("click", startOver);
byId("sound").addEventListener("click", toggleSound);
byId("verify-yes").addEventListener("click", () => answerAsDanny("yes"));
byId("verify-no").addEventListener("click", () => answerAsDanny("no"));
byId("call-picker").addEventListener("change", startOver);
byId("family-language").addEventListener("change", startOver);

resetScreen();
loadCalls();
drawIcons();
