/*
  family.js — The "Your family" part of the dashboard.

  How it fits in: index.html loads this file before app.js. Once app.js has
  checked the login, it calls loadFamily(), which asks our server for
  everyone this family protects (GET /api/family, see app/family.py) and
  shows, for each senior:
    - whether they're protected right now, with a Pause / Turn back on button
      (POST /api/enrollments/{id}/pause and /resume)
    - who gets the alerts
    - their past calls, newest first, with the score. Tapping a call opens
      its details: the reasons, who the caller said they were, and the Tavily
      links (GET /api/calls/{id})
  If the family hasn't signed anyone up yet, we show the sign-up form instead.

  It uses sendRequest() from app.js, which adds the login token for us.
*/

// What each status means, in plain words, for the badge next to the name.
const FAMILY_STATUS_LABELS = {
  active: "Protected",
  paused: "Paused",
  pending: "Waiting for their YES",
  declined: "Said no",
  expired: "Didn't answer",
  revoked: "Turned off",
};

// What each verdict means, for the call history.
const VERDICT_LABELS = {
  likely_scam: "Likely scam",
  suspicious: "Suspicious",
  safe: "Looked safe",
};

// Scores from here up are scams (the same line as detector.ALERT_FROM),
// and from WATCH_FROM up we call them out as worth a look.
const ALERT_FROM = 70;
const WATCH_FROM = 40;

/**
 * Make an element with a class and some text, so building the list stays short.
 *
 * Input:  tag — like "p"; className — like "hint" (or ""); text — what it says
 * Output: the new element
 * Example: makeElement("p", "hint", "No calls yet.")  gives you  <p class="hint">No calls yet.</p>
 */
function makeElement(tag, className, text = "") {
  const element = document.createElement(tag);
  if (className) {
    element.className = className;
  }
  element.textContent = text;
  return element;
}

/**
 * Write a phone number the way people read it.
 *
 * Input:  phone — like "+13055550142"
 * Output: like "(305) 555-0142". Numbers we don't recognize come back as they are.
 * Example: formatPhone("+13055550142")  gives you  "(305) 555-0142"
 */
function formatPhone(phone) {
  const match = /^\+1(\d{3})(\d{3})(\d{4})$/.exec(phone || "");
  if (!match) {
    return phone || "Unknown number";
  }
  return `(${match[1]}) ${match[2]}-${match[3]}`;
}

/**
 * Write a saved time (in UTC) as a short local date and time.
 *
 * Input:  text — like "2026-10-21T18:04:05+00:00"
 * Output: like "Oct 21, 2026, 2:04 PM" (in the viewer's own time zone)
 * Example: formatWhen("2026-10-21T18:04:05+00:00")  gives you  "Oct 21, 2026, 2:04 PM" in Miami
 */
function formatWhen(text) {
  return new Date(text).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

/**
 * Pick the color for a score: red for scams, gold for "take a look", plain for safe.
 *
 * Input:  score — 0 to 100, or null if the call never got checked
 * Output: a class name from styles.css
 * Example: scoreClass(92)  gives you  "score score-high"
 */
function scoreClass(score) {
  if (score === null || score === undefined) {
    return "score";
  }
  if (score >= ALERT_FROM) {
    return "score score-high";
  }
  if (score >= WATCH_FROM) {
    return "score score-mid";
  }
  return "score score-low";
}

/**
 * Ask the server for everyone this family protects, and show them.
 * If nobody's signed up yet, show the sign-up form instead.
 *
 * Input:  nothing
 * Output: nothing; it updates the page.
 * Example: Ana protects Rosa  gives you  Rosa's card with her calls
 */
async function loadFamily() {
  const section = document.getElementById("family");
  const errorElement = document.getElementById("family-error");
  errorElement.textContent = "";

  const { ok, data } = await sendRequest("/api/family");
  if (!ok) {
    // We can still let them sign someone up, even if the list didn't load.
    errorElement.textContent = data.error || "We couldn't load your family. Please refresh the page.";
    section.hidden = false;
    return;
  }

  const seniors = data.seniors || [];
  section.hidden = seniors.length === 0;
  // Nobody to show yet: the sign-up form is the whole page. (If they're
  // in the middle of signing someone up, leave that panel alone.)
  const signingUp = !document.getElementById("consent-status").hidden;
  if (seniors.length === 0 && !signingUp) {
    document.getElementById("signup-form").hidden = false;
  }

  const list = document.getElementById("family-list");
  list.replaceChildren();
  for (const senior of seniors) {
    list.appendChild(seniorCard(senior));
  }
}

/**
 * Build one senior's card: name, status, the pause button, and their calls.
 *
 * Input:  senior — one entry from GET /api/family
 * Output: the card element
 * Example: seniorCard({senior_name: "Rosa", status: "active", calls: [...]})
 *          gives you "Rosa · Protected", a Pause button and her call history
 */
function seniorCard(senior) {
  const card = makeElement("article", "senior");

  const top = makeElement("div", "senior-top");
  top.appendChild(makeElement("h3", "", senior.senior_name));
  top.appendChild(
    makeElement("span", `status-pill status-${senior.status}`, FAMILY_STATUS_LABELS[senior.status] || senior.status)
  );
  card.appendChild(top);

  card.appendChild(
    makeElement("p", "hint", `Alerts go to ${senior.family_name} (${senior.family_phone}).`)
  );

  // Only seniors who said YES can be paused or turned back on.
  if (senior.status === "active" || senior.status === "paused") {
    card.appendChild(pauseButton(senior));
  }

  card.appendChild(makeElement("h4", "", "Past calls"));
  if (senior.calls.length === 0) {
    card.appendChild(makeElement("p", "hint", "No calls yet."));
  } else {
    const calls = makeElement("ul", "call-list");
    for (const call of senior.calls) {
      calls.appendChild(callRow(call));
    }
    card.appendChild(calls);
  }
  return card;
}

/**
 * Build the Pause / Turn back on button for one senior, with a line that
 * says what pausing means.
 *
 * Input:  senior — one entry from GET /api/family
 * Output: an element with the button and the line under it
 * Example: an active senior  gives you  "Pause protection" and
 *          "Calls still ring like normal, but we won't listen or send alerts."
 */
function pauseButton(senior) {
  const wrapper = makeElement("div", "pause");
  const paused = senior.status === "paused";

  const button = makeElement(
    "button",
    paused ? "button-small" : "button-small button-outline",
    paused ? "Turn protection back on" : "Pause protection"
  );
  button.type = "button";
  button.addEventListener("click", () => togglePause(senior, button));
  wrapper.appendChild(button);

  wrapper.appendChild(
    makeElement(
      "p",
      "hint",
      paused
        ? `Protection is paused. ${senior.senior_name}'s calls ring like normal, and we aren't listening.`
        : "Calls still ring like normal, but we won't listen or send alerts."
    )
  );
  return wrapper;
}

/**
 * Pause protection for a senior, or turn it back on, then refresh the list.
 *
 * Input:  senior — one entry from GET /api/family; button — the one they tapped
 * Output: nothing; it updates the page.
 * Example: tap "Pause protection" on Rosa  gives you  Rosa · Paused
 */
async function togglePause(senior, button) {
  const action = senior.status === "paused" ? "resume" : "pause";
  // Stops a double tap from sending it twice.
  button.disabled = true;
  const { ok, data } = await sendRequest(`/api/enrollments/${senior.id}/${action}`, { method: "POST" });
  if (!ok) {
    document.getElementById("family-error").textContent = data.error || "That didn't work. Please try again.";
    button.disabled = false;
    return;
  }
  await loadFamily();
}

/**
 * Build one row in the call history. Tapping it opens the call's details.
 *
 * Input:  call — one call from GET /api/family
 * Output: the list item
 * Example: callRow({risk_score: 92, verdict: "likely_scam", alerted: true, ...})
 *          gives you "Oct 21, 2:04 PM · (305) 555-0142 · 92 Likely scam · Family alerted"
 */
function callRow(call) {
  const item = makeElement("li", "call");

  const button = makeElement("button", "call-button");
  button.type = "button";
  // Tells screen readers whether the details are open.
  button.setAttribute("aria-expanded", "false");

  const score = call.risk_score === null ? "–" : String(call.risk_score);
  button.appendChild(makeElement("span", scoreClass(call.risk_score), score));

  const words = makeElement("span", "call-words");
  words.appendChild(makeElement("span", "call-when", formatWhen(call.started_at)));
  words.appendChild(makeElement("span", "call-from", formatPhone(call.caller_number)));
  const verdict = VERDICT_LABELS[call.verdict] || "Not checked";
  const live = call.status === "live" ? " · On the phone now" : "";
  const alerted = call.alerted ? " · Family alerted" : "";
  words.appendChild(makeElement("span", "call-verdict", verdict + live + alerted));
  button.appendChild(words);
  item.appendChild(button);

  const details = makeElement("div", "call-details");
  details.hidden = true;
  item.appendChild(details);

  button.addEventListener("click", () => toggleCallDetails(call.id, button, details));
  return item;
}

/**
 * Open or close one call's details. The first time it opens, we ask the
 * server for them (GET /api/calls/{id}).
 *
 * Input:  callId — which call; button — the row they tapped; details — where to show them
 * Output: nothing; it updates the page.
 * Example: tap the 92 call  gives you  its reasons and the FTC link
 */
async function toggleCallDetails(callId, button, details) {
  const opening = details.hidden;
  details.hidden = !opening;
  button.setAttribute("aria-expanded", String(opening));
  if (!opening || details.dataset.loaded) {
    return;
  }

  details.replaceChildren(makeElement("p", "hint", "Loading…"));
  const { ok, data } = await sendRequest(`/api/calls/${callId}`);
  if (!ok) {
    details.replaceChildren(makeElement("p", "error", data.error || "We couldn't load this call."));
    return;
  }
  details.dataset.loaded = "yes";
  showCallDetails(data, details);
}

/**
 * Fill in a call's details: who the caller said they were, why we were
 * worried, and the Tavily links we found.
 *
 * Input:  call — from GET /api/calls/{id}; details — where to show them
 * Output: nothing; it fills in details.
 * Example: the grandson call  gives you  "Said they were: grandson Danny",
 *          the reasons, and links like "consumer.ftc.gov: Grandparent scams"
 */
function showCallDetails(call, details) {
  details.replaceChildren();

  if (call.claimed_identity) {
    details.appendChild(makeElement("p", "", `Said they were: ${call.claimed_identity}`));
  }

  if (call.reasons.length > 0) {
    details.appendChild(makeElement("h5", "", "Why we were worried"));
    const reasons = makeElement("ul", "reasons");
    for (const reason of call.reasons) {
      reasons.appendChild(makeElement("li", "", reason));
    }
    details.appendChild(reasons);
  } else {
    details.appendChild(makeElement("p", "hint", "Nothing looked wrong on this call."));
  }

  const links = call.sources.filter((source) => /^https?:\/\//.test(source.url));
  if (links.length > 0) {
    details.appendChild(makeElement("h5", "", "What we found online"));
    const list = makeElement("ul", "sources");
    for (const source of links) {
      const item = document.createElement("li");
      const link = makeElement("a", "", source.title || source.url);
      link.href = source.url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      item.appendChild(link);
      item.appendChild(makeElement("span", "hint", ` (${new URL(source.url).hostname.replace(/^www\./, "")})`));
      list.appendChild(item);
    }
    details.appendChild(list);
  }

  if (call.alerted_at) {
    details.appendChild(makeElement("p", "hint", `We alerted the family at ${formatWhen(call.alerted_at)}.`));
  }
}

/**
 * Show the sign-up form again, to protect another person.
 *
 * Example: tap "Protect someone else"  gives you  the empty sign-up form
 */
function showSignupForm() {
  const form = document.getElementById("signup-form");
  form.reset();
  form.hidden = false;
  document.getElementById("consent-status").hidden = true;
  form.scrollIntoView({ behavior: "smooth" });
}

document.getElementById("show-signup").addEventListener("click", showSignupForm);
