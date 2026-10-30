/*
  family.js — The "Your family" part of the dashboard.

  How it fits in: index.html loads this file before app.js. Once app.js has
  checked the login, it calls loadFamily(), which asks our server for
  everyone this family protects (GET /api/family, see app/family.py) and
  shows everyone grouped by who they are to you (Mom, Dad, Grandma... and
  Other for everyone else), and for each senior:
    - who they are to you, which they can change right on the card
      (POST /api/enrollments/{id}/relationship)
    - whether they're protected right now, with a Pause / Turn back on button
      (POST /api/enrollments/{id}/pause and /resume)
    - who gets the alerts
    - their past calls, newest first, with the score. Tapping a call opens
      its details: the reasons, who the caller said they were, and the Tavily
      links (GET /api/calls/{id})
    - "Was this a scam?" in each call's details, so the family can tell us
      if we got it right (POST /api/calls/{id}/answer)
    - "Report and block" for scam calls: the details ready to paste into the
      FTC's report form, and what to do if the number calls again: warn us
      or block it (POST /api/calls/{id}/scam-list)
  If the family hasn't signed anyone up yet, we show the sign-up form instead.

  It uses sendRequest() from app.js, which adds the login token for us,
  setBusy() / setReady() from busy.js for the buttons, and t() from i18n.js
  for the words, in English or Spanish. When the language changes, we load
  the list again in the new language.
*/

// The words for each status, for the badge next to the name (keys in strings.js).
const FAMILY_STATUS_LABELS = {
  active: "family.statusActive",
  paused: "family.statusPaused",
  pending: "family.statusPending",
  declined: "family.statusDeclined",
  expired: "family.statusExpired",
  revoked: "family.statusRevoked",
};

// Who a senior can be to the family, in the order "Your family" shows
// them (the same list as consent.RELATIONSHIPS). The words are
// "relationship.mom" and so on in strings.js.
const RELATIONSHIPS = [
  "mom",
  "dad",
  "grandma",
  "grandpa",
  "wife",
  "husband",
  "daughter",
  "son",
  "sister",
  "brother",
  "aunt",
  "uncle",
  "other",
];

// What each verdict means, for the call history.
const VERDICT_LABELS = {
  likely_scam: "family.verdictLikelyScam",
  suspicious: "family.verdictSuspicious",
  safe: "family.verdictSafe",
};

// How we show the family's own answer, in the call list.
const FAMILY_ANSWER_LABELS = {
  scam: "family.youSaidScam",
  not_scam: "family.youSaidNotScam",
};

// The choices for "If this number calls again": the words on the button,
// and what that choice means (keys in strings.js).
const SCAM_LIST_CHOICES = [
  { choice: "none", label: "report.choiceNone", means: "report.meansNone" },
  { choice: "warn", label: "report.choiceWarn", means: "report.meansWarn" },
  { choice: "block", label: "report.choiceBlock", means: "report.meansBlock" },
];

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
    return phone || t("family.unknownNumber");
  }
  return `(${match[1]}) ${match[2]}-${match[3]}`;
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
  const list = document.getElementById("family-list");
  const errorElement = document.getElementById("family-error");
  errorElement.textContent = "";

  // The first time, say we're loading, so the page doesn't look empty.
  // (Later refreshes keep the old list up until the new one is ready.)
  if (list.childElementCount === 0) {
    section.hidden = false;
    list.replaceChildren(makeElement("p", "hint", t("family.loading")));
  }

  const { ok, data } = await sendRequest("/api/family");
  if (!ok) {
    // We can still let them sign someone up, even if the list didn't load.
    list.replaceChildren();
    errorElement.textContent = data.error;
    section.hidden = false;
    // We can still let them sign someone up, even if the list didn't load.
    document.getElementById("signup-form").hidden = false;
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

  list.replaceChildren();
  for (const [relationship, group] of groupByRelationship(seniors)) {
    list.appendChild(makeElement("h3", "family-group", t(`relationship.${relationship}`)));
    for (const senior of group) {
      list.appendChild(seniorCard(senior));
    }
  }
}

/**
 * Put the seniors into groups by who they are to the family, in the
 * RELATIONSHIPS order, with Other last. Inside a group, the newest sign-up
 * stays first.
 *
 * Input:  seniors — the list from GET /api/family
 * Output: [relationship, [seniors]] pairs, only for groups that have someone
 * Example: groupByRelationship([rosa (grandma), luis (other), maria (mom)])
 *          gives you  [["mom", [maria]], ["grandma", [rosa]], ["other", [luis]]]
 */
function groupByRelationship(seniors) {
  const groups = [];
  for (const relationship of RELATIONSHIPS) {
    // Anything we don't know goes under Other.
    const group = seniors.filter(
      (senior) => (RELATIONSHIPS.includes(senior.relationship) ? senior.relationship : "other") === relationship
    );
    if (group.length > 0) {
      groups.push([relationship, group]);
    }
  }
  return groups;
}

/**
 * The "Who are they to you?" list on a senior's card. Picking a new answer
 * saves it, and the card moves to its new group.
 *
 * Input:  senior — one entry from GET /api/family
 * Output: the label with the list inside
 * Example: Rosa, saved as Other  gives you  "Who are they to you? [Other]";
 *          pick Grandma and she moves under "Grandma"
 */
function relationshipPicker(senior) {
  const label = makeElement("label", "relationship-picker");
  label.appendChild(makeElement("span", "", t("dash.whoToYou")));
  const select = document.createElement("select");
  for (const relationship of RELATIONSHIPS) {
    const option = makeElement("option", "", t(`relationship.${relationship}`));
    option.value = relationship;
    select.appendChild(option);
  }
  select.value = RELATIONSHIPS.includes(senior.relationship) ? senior.relationship : "other";
  select.addEventListener("change", async () => {
    // Stops a second change while this one is still saving.
    select.disabled = true;
    const { ok, data } = await sendRequest(`/api/enrollments/${senior.id}/relationship`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ relationship: select.value }),
    });
    if (!ok) {
      document.getElementById("family-error").textContent = data.error;
      select.value = senior.relationship;
      select.disabled = false;
      return;
    }
    await loadFamily();
  });
  label.appendChild(select);
  return label;
}

/**
 * Build one senior's card: name, status, who they are to you, the pause
 * button, and their calls.
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
    makeElement(
      "span",
      `status-pill status-${senior.status}`,
      FAMILY_STATUS_LABELS[senior.status] ? t(FAMILY_STATUS_LABELS[senior.status]) : senior.status
    )
  );
  card.appendChild(top);

  card.appendChild(
    makeElement("p", "hint", t("family.alertsGoTo", { name: senior.family_name, phone: senior.family_phone }))
  );
  card.appendChild(relationshipPicker(senior));

  // Only seniors who said YES can be paused or turned back on, and only
  // they have phone setup steps (setup.html).
  if (senior.status === "active" || senior.status === "paused") {
    card.appendChild(pauseButton(senior));
    const setup = makeElement("a", "setup-card-link", t("family.setupSteps"));
    setup.href = `/setup/${senior.id}`;
    card.appendChild(setup);
  }
  card.appendChild(seniorActions(senior));

  card.appendChild(makeElement("h4", "", t("family.pastCalls")));
  if (senior.calls.length === 0) {
    card.appendChild(makeElement("p", "hint", t("family.noCalls")));
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
 * The buttons on every senior's card: "Call again" while we're still waiting
 * for them to press 1, and a red "Remove" that deletes them for good.
 *
 * Input:  senior, one entry from GET /api/family
 * Output: an element with the buttons and a line for what happened
 * Example: a senior still waiting on our call  gives you  "Call again" and "Remove"
 */
function seniorActions(senior) {
  const wrapper = makeElement("div", "answer-buttons");
  const note = makeElement("p", "hint");

  if (senior.status === "pending" && senior.ask_by === "call") {
    const again = makeElement("button", "button-small", t("family.callAgain"));
    again.type = "button";
    again.addEventListener("click", async () => {
      setBusy(again, t("dash.busyCallAgain"));
      const { ok, data } = await sendRequest(`/api/enrollments/${senior.id}/call-again`, { method: "POST" });
      setReady(again);
      note.textContent = ok ? t("dash.calledAgain") : data.error;
    });
    wrapper.appendChild(again);
  }

  const remove = makeElement("button", "button-small button-danger", t("family.remove"));
  remove.type = "button";
  wrapper.appendChild(remove);

  // Removing can't be undone, so the first tap only asks "Are you sure?",
  // right on the card, with a red button to go ahead and one to back out.
  const question = makeElement("div", "remove-question");
  question.hidden = true;
  question.appendChild(makeElement("p", "hint", t("family.removeConfirm", { name: senior.senior_name })));
  const yes = makeElement("button", "button-small button-danger", t("family.removeYes"));
  yes.type = "button";
  const keep = makeElement("button", "button-small button-outline", t("family.removeKeep"));
  keep.type = "button";
  question.append(yes, " ", keep);

  remove.addEventListener("click", () => {
    wrapper.hidden = true;
    question.hidden = false;
    note.textContent = "";
  });
  keep.addEventListener("click", () => {
    question.hidden = true;
    wrapper.hidden = false;
  });
  yes.addEventListener("click", async () => {
    // Stops a double tap from sending it twice.
    setBusy(yes, t("family.busyRemove"));
    const { ok, data } = await sendRequest(`/api/enrollments/${senior.id}`, { method: "DELETE" });
    if (!ok) {
      setReady(yes);
      note.textContent = data.error;
      return;
    }
    showRemovedNotice(data);
    await loadFamily();
  });

  const box = makeElement("div", "senior-actions");
  box.append(wrapper, question, note);
  return box;
}

/**
 * After a Remove, say what's left to do: their phone still forwards calls
 * to Scam Shield (we let them ring through without listening) until
 * someone turns forwarding off.
 *
 * Input:  removed — what DELETE /api/enrollments/{id} sent back,
 *                   e.g. {removed: "Rosa", phone_type: "cell"}
 * Output: nothing; it shows the note above "Your family".
 * Example: showRemovedNotice({removed: "Rosa", phone_type: "cell"})
 *          gives you  "Rosa was removed... dial ##002# (Verizon: *73)."
 */
function showRemovedNotice(removed) {
  const key = removed.phone_type === "landline" ? "family.removedLandline" : "family.removedCell";
  const notice = document.getElementById("family-notice");
  notice.textContent = t(key, { name: removed.removed });
  notice.hidden = false;
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
    paused ? t("family.resume") : t("family.pause")
  );
  button.type = "button";
  button.addEventListener("click", () => togglePause(senior, button));
  wrapper.appendChild(button);

  wrapper.appendChild(
    makeElement(
      "p",
      "hint",
      paused
        ? t("family.pausedNote", { name: senior.senior_name })
        : t("family.pauseNote")
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
  setBusy(button, action === "pause" ? t("family.busyPause") : t("family.busyResume"));
  const { ok, data } = await sendRequest(`/api/enrollments/${senior.id}/${action}`, { method: "POST" });
  if (!ok) {
    document.getElementById("family-error").textContent = data.error;
    setReady(button);
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
  words.appendChild(makeElement("span", "call-verdict", verdictLine(call)));
  button.appendChild(words);
  item.appendChild(button);

  const details = makeElement("div", "call-details");
  details.hidden = true;
  item.appendChild(details);

  button.addEventListener("click", () => toggleCallDetails(call.id, button, details));
  return item;
}

/**
 * The short line under each call: what we thought, and what the family said.
 *
 * Input:  call — one call from GET /api/family or GET /api/calls/{id}
 * Output: the line of text
 * Example: verdictLine({verdict: "likely_scam", alerted: true, family_answer: "scam", ...})
 *          gives you  "Likely scam · Family alerted · You said: scam"
 */
function verdictLine(call) {
  // A blocked call never rang, so there's no score to talk about.
  if (call.scam_list === "block") {
    return t("family.blockedLine");
  }
  const parts = [t(VERDICT_LABELS[call.verdict] || "family.notChecked")];
  if (call.scam_list === "warn") {
    parts.push(t("family.reportedNumber"));
  }
  if (call.status === "live") {
    parts.push(t("family.onThePhone"));
  }
  if (call.alerted) {
    parts.push(t("family.alerted"));
  }
  if (call.family_answer) {
    parts.push(t(FAMILY_ANSWER_LABELS[call.family_answer]));
  }
  return parts.join(" · ");
}

/**
 * Open or close one call's details. The first time it opens, we ask the
 * server for them (GET /api/calls/{id}). If that didn't work, the next tap
 * tries again.
 *
 * Input:  callId — which call; button — the row they tapped; details — where to show them
 * Output: nothing; it updates the page.
 * Example: tap the 92 call  gives you  its reasons and the FTC link
 */
async function toggleCallDetails(callId, button, details) {
  // If it didn't load last time, a tap tries again instead of closing it.
  const retrying = details.dataset.failed === "yes";
  const opening = details.hidden || retrying;
  details.hidden = !opening;
  button.setAttribute("aria-expanded", String(opening));
  if (!opening || details.dataset.loaded) {
    return;
  }

  delete details.dataset.failed;
  details.replaceChildren(makeElement("p", "hint", t("family.loadingCall")));
  const { ok, data } = await sendRequest(`/api/calls/${callId}`);
  if (!ok) {
    details.dataset.failed = "yes";
    details.replaceChildren(
      makeElement("p", "error", data.error),
      makeElement("p", "hint", t("family.tapToRetry"))
    );
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

  if (call.scam_list === "block") {
    details.appendChild(
      makeElement("p", "", t("family.blockedDetails"))
    );
    details.appendChild(reportAndBlock(call, details));
    return;
  }

  if (call.claimed_identity) {
    details.appendChild(makeElement("p", "", t("family.saidTheyWere", { who: call.claimed_identity })));
  }

  if (call.reasons.length > 0) {
    details.appendChild(makeElement("h5", "", t("family.whyWorried")));
    const reasons = makeElement("ul", "reasons");
    for (const reason of call.reasons) {
      reasons.appendChild(makeElement("li", "", reason));
    }
    details.appendChild(reasons);
  } else {
    details.appendChild(makeElement("p", "hint", t("family.nothingWrong")));
  }

  const links = call.sources.filter((source) => /^https?:\/\//.test(source.url));
  if (links.length > 0) {
    details.appendChild(makeElement("h5", "", t("family.foundOnline")));
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
    details.appendChild(makeElement("p", "hint", t("family.alertedAt", { time: formatWhen(call.alerted_at) })));
  }

  // Only calls we scored can be right or wrong.
  if (call.risk_score !== null) {
    details.appendChild(askWasItAScam(call, details));
  }

  // Report and block, once it looks like a scam (or the family says so, or
  // the number is already on their list).
  const looksLikeAScam =
    call.verdict === "likely_scam" || call.family_answer === "scam" || call.number_on_list !== null;
  if (call.caller_number && looksLikeAScam) {
    details.appendChild(reportAndBlock(call, details));
  }
}

/**
 * Write up a call for the FTC's report form, so the family can paste it
 * instead of remembering every detail.
 *
 * Input:  call — from GET /api/calls/{id}
 * Output: the text, one fact per line
 * Example: the grandson call  gives you  "Scam phone call
 *          When: Oct 21, 2026, 10:47 PM
 *          Number that called: (305) 555-0142 ..."
 */
function ftcReportText(call) {
  const lines = [
    t("report.textTitle"),
    t("report.textWhen", { time: formatWhen(call.started_at) }),
    t("report.textNumber", { number: formatPhone(call.caller_number) }),
  ];
  if (call.claimed_identity) {
    lines.push(t("report.textWho", { who: call.claimed_identity }));
  }
  if (call.reasons.length > 0) {
    lines.push(t("report.textWhat", { what: call.reasons.join("; ") }));
  }
  if (call.risk_score !== null) {
    lines.push(t("report.textScore", { score: call.risk_score }));
  }
  return lines.join("\n");
}

/**
 * Build the "Report and block" section: the FTC report (details ready to
 * copy, and a link to the form), what to do if the number calls again, and
 * how to block it on the phone itself.
 *
 * Input:  call — from GET /api/calls/{id}; details — the call's details area
 * Output: the section element
 * Example: the grandson call  gives you  "Copy the details", "Open the FTC
 *          report form", and "Do nothing / Warn us right away / Block it"
 */
function reportAndBlock(call, details) {
  const box = makeElement("div", "report-and-block");
  box.appendChild(makeElement("h5", "", t("report.title")));
  box.appendChild(makeElement("p", "hint", t("report.hint")));

  // The text sits in a box they can read (and copy by hand if Copy doesn't work).
  const text = makeElement("textarea", "report-text");
  text.readOnly = true;
  text.rows = 5;
  text.value = ftcReportText(call);
  text.setAttribute("aria-label", t("report.textAria"));
  box.appendChild(text);

  const actions = makeElement("div", "answer-buttons");
  const copy = makeElement("button", "button-small", t("report.copy"));
  copy.type = "button";
  copy.addEventListener("click", () => copyReport(text, copy));
  const open = makeElement("a", "button button-small button-outline", t("report.openForm"));
  // The FTC's English or Spanish site, to match the report we wrote.
  open.href = t("report.url");
  open.target = "_blank";
  open.rel = "noopener noreferrer";
  actions.append(copy, open);
  box.appendChild(actions);

  box.appendChild(makeElement("h5", "", t("report.ifAgain")));
  const choices = makeElement("div", "answer-buttons");
  const picked = call.number_on_list || "none";
  for (const option of SCAM_LIST_CHOICES) {
    const button = makeElement("button", "button-small button-outline", t(option.label));
    button.type = "button";
    button.setAttribute("aria-pressed", String(picked === option.choice));
    button.addEventListener("click", () => sendScamListChoice(call.id, option.choice, button, details));
    choices.appendChild(button);
  }
  box.appendChild(choices);
  const means = SCAM_LIST_CHOICES.find((option) => option.choice === picked).means;
  box.appendChild(makeElement("p", "hint", `${t(means)} ${t("report.onlyYours")}`));
  box.appendChild(makeElement("p", "error scam-list-error", ""));

  box.appendChild(phoneBlockSteps());
  return box;
}

/**
 * Copy the FTC report text, and say it worked (or how to copy it by hand).
 *
 * Input:  text — the report's text box; button — the Copy button
 * Example: tap "Copy the details"  gives you  "Copied!" for a moment
 */
async function copyReport(text, button) {
  try {
    await navigator.clipboard.writeText(text.value);
    button.textContent = t("report.copied");
  } catch (error) {
    // Some browsers don't allow copying from a page. Select it so a long
    // press (or Ctrl+C) copies it.
    text.select();
    button.textContent = t("report.selectInstead");
  }
  setTimeout(() => {
    button.textContent = t("report.copy");
  }, 2500);
}

/**
 * Save what to do if a number calls again, then show the call again with
 * that choice picked.
 *
 * Input:  callId — the call the number came from; choice — "warn", "block" or "none";
 *         button — the one they tapped; details — the call's details area
 * Output: nothing; it updates the page.
 * Example: tap "Block it"  gives you  "Block it" picked, and the number blocked
 */
async function sendScamListChoice(callId, choice, button, details) {
  setBusy(button, t("family.saving"));
  const { ok, data } = await sendRequest(`/api/calls/${callId}/scam-list`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ choice }),
  });
  if (!ok) {
    setReady(button);
    details.querySelector(".scam-list-error").textContent = data.error;
    return;
  }
  showCallDetails(data, details);
}

/**
 * The steps to block a number on the phone itself, folded up until tapped.
 *
 * Calls that forward to Scam Shield come to us first, so the phone's own
 * block list never sees them: "Block it" above is what stops those. Blocking
 * on the phone still helps with scam TEXTS, and with calls that don't come
 * through Scam Shield.
 *
 * Output: a <details> element ("Block it on the phone too")
 * Example: tap it  gives you  the iPhone and Android steps
 */
function phoneBlockSteps() {
  const box = makeElement("details", "phone-steps");
  box.appendChild(makeElement("summary", "", t("report.phoneTitle")));
  box.appendChild(makeElement("p", "hint", t("report.phoneNote")));

  const steps = [
    ["iPhone", t("report.iphone")],
    ["Android", t("report.android")],
  ];
  const list = makeElement("ul", "reasons");
  for (const [phone, how] of steps) {
    const item = document.createElement("li");
    item.appendChild(makeElement("strong", "", `${phone}: `));
    item.appendChild(document.createTextNode(how));
    list.appendChild(item);
  }
  box.appendChild(list);
  return box;
}

/**
 * Build the "Was this a scam?" question with its two buttons. The button
 * matching the family's answer shows as picked, and they can change it.
 *
 * Input:  call — from GET /api/calls/{id}; details — the details area it goes in
 * Output: the element with the question and buttons
 * Example: a call they haven't answered  gives you  "Was this a scam?"
 *          with "Yes, it was a scam" and "No, false alarm"
 */
function askWasItAScam(call, details) {
  const box = makeElement("div", "was-it-a-scam");
  box.appendChild(makeElement("h5", "", t("family.wasItAScam")));

  const choices = [
    { answer: "scam", label: t("family.yesScam") },
    { answer: "not_scam", label: t("family.noFalseAlarm") },
  ];
  const buttons = makeElement("div", "answer-buttons");
  for (const choice of choices) {
    const button = makeElement("button", "button-small button-outline", choice.label);
    button.type = "button";
    // aria-pressed tells screen readers (and styles.css) which one they picked.
    button.setAttribute("aria-pressed", String(call.family_answer === choice.answer));
    button.addEventListener("click", () => sendAnswer(call.id, choice.answer, button, details));
    buttons.appendChild(button);
  }
  box.appendChild(buttons);

  const note = call.family_answer
    ? t("family.answerThanks")
    : t("family.answerHelps");
  box.appendChild(makeElement("p", "hint", note));
  box.appendChild(makeElement("p", "error answer-error", ""));
  return box;
}

/**
 * Send the family's "Was this a scam?" answer, then show the call again with
 * it picked, and update the line in the call list.
 *
 * Input:  callId — which call; answer — "scam" or "not_scam";
 *         button — the one they tapped; details — the call's details area
 * Output: nothing; it updates the page.
 * Example: tap "No, false alarm"  gives you  that button picked, and
 *          "You said: false alarm" in the call list
 */
async function sendAnswer(callId, answer, button, details) {
  setBusy(button, t("family.saving"));
  const { ok, data } = await sendRequest(`/api/calls/${callId}/answer`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ answer }),
  });
  if (!ok) {
    setReady(button);
    details.querySelector(".answer-error").textContent = data.error;
    return;
  }
  showCallDetails(data, details);
  details.closest(".call").querySelector(".call-verdict").textContent = verdictLine(data);
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
// Build the list again in the new language when they flip the switch.
document.addEventListener("language-switched", () => {
  if (!document.getElementById("dashboard").hidden) {
    loadFamily();
  }
});
