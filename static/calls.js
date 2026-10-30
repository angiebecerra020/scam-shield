/*
  calls.js — Fills in the Call Log page (calls.html).

  How it fits in: it asks GET /api/family for everyone this family protects
  and their calls (app/family.py), puts every call in one list, newest first,
  and counts the scams caught and alerts sent. Tapping a call asks
  GET /api/calls/{id} for the reasons, who the caller said they were, and
  the Tavily links. We only ever set textContent, never HTML, so nothing a
  caller says can sneak code onto the page.
*/

// Every call, with its senior's name, from the last load.
let allCalls = [];
// Which filter button is on: "all", "scam", "safe" or "unknown".
let currentFilter = "all";

/**
 * Make an element with a class and some text.
 *
 * Example: makeEl("p", "hint", "Hello")  gives you  <p class="hint">Hello</p>
 */
function makeEl(tag, className, text) {
  const element = document.createElement(tag);
  if (className) {
    element.className = className;
  }
  if (text !== undefined) {
    element.textContent = text;
  }
  return element;
}

/**
 * Ask our server for something, with the login token.
 *
 * Example: await askServer("/api/family")  gives you  {ok: true, data: {seniors: [...]}}
 */
async function askServer(url) {
  const headers = await loginHeaders();
  const { ok, status, data } = await fetchJson(url, { headers });
  if (status === 401) {
    window.location.replace("/login");
  }
  return { ok, data };
}

/**
 * Which group a call belongs in, for the filters.
 *
 * Example: groupOf({verdict: "likely_scam"})  gives you  "scam"
 *          groupOf({verdict: null})           gives you  "unknown"
 */
function groupOf(call) {
  if (call.verdict === "likely_scam" || call.verdict === "suspicious") {
    return "scam";
  }
  if (call.verdict === "safe") {
    return "safe";
  }
  return "unknown";
}

/**
 * A short, friendly date and time, like "Oct 30, 9:33 AM".
 *
 * Example: niceTime("2026-10-30T13:33:17+00:00")  gives you  "Oct 30, 9:33 AM" (in Florida)
 */
function niceTime(text) {
  const date = new Date(text);
  if (Number.isNaN(date.getTime())) {
    return "";
  }
  return date.toLocaleString(currentLanguage === "es" ? "es-US" : "en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

/**
 * Fill in the three numbers at the top.
 *
 * Example: 5 calls, 2 scams, 1 alert  gives you  "5", "2", "1"
 */
function showStats() {
  const checked = allCalls.filter((call) => call.risk_score !== null && call.risk_score !== undefined);
  document.getElementById("stat-total").textContent = String(checked.length);
  document.getElementById("stat-scams").textContent = String(allCalls.filter((call) => groupOf(call) === "scam").length);
  document.getElementById("stat-alerts").textContent = String(allCalls.filter((call) => call.alerted).length);
}

/**
 * Load the details of one call (reasons, who they said they were, Tavily
 * links) into its row, the first time it's tapped.
 *
 * Example: tap the 92 call  gives you  "Why we were worried: Asks for gift cards..."
 */
async function showDetails(call, box) {
  box.replaceChildren(makeEl("p", "hint", t("calls.loading")));
  const { ok, data } = await askServer(`/api/calls/${encodeURIComponent(call.id)}`);
  box.replaceChildren();
  if (!ok) {
    box.appendChild(makeEl("p", "error", t("calls.error")));
    return;
  }
  if (data.claimed_identity) {
    const said = makeEl("p");
    said.append(makeEl("strong", "", t("calls.claimed") + " "), data.claimed_identity);
    box.appendChild(said);
  }
  if (data.reasons && data.reasons.length > 0) {
    box.appendChild(makeEl("p", "call-detail-title", t("calls.why")));
    const list = makeEl("ul", "reasons");
    for (const reason of data.reasons) {
      list.appendChild(makeEl("li", "", reason));
    }
    box.appendChild(list);
  }
  const sources = (data.sources || []).filter((source) => /^https?:\/\//.test(source.url || ""));
  if (sources.length > 0) {
    box.appendChild(makeEl("p", "call-detail-title", t("calls.sources")));
    const list = makeEl("ul", "reasons");
    for (const source of sources) {
      const item = makeEl("li");
      const link = makeEl("a", "", source.title || source.url);
      link.href = source.url;
      link.target = "_blank";
      link.rel = "noopener";
      item.appendChild(link);
      list.appendChild(item);
    }
    box.appendChild(list);
  }
  if (data.family_answer) {
    const answer = data.family_answer === "scam" ? t("calls.saidScam") : t("calls.saidNotScam");
    box.appendChild(makeEl("p", "hint", `${t("calls.familySaid")} ${answer}`));
  }
}

/**
 * One row in the log: the score circle, who called, when, and the status.
 * Tapping it opens the details.
 *
 * Example: a 92 call  gives you  a red "92" circle, "(561) 555-0199 to Rosa", "Likely scam · Family alerted"
 */
function callRow(call) {
  const group = groupOf(call);
  const row = makeEl("li", `call-row call-${group}`);
  const button = makeEl("button", "call-row-button");
  button.type = "button";
  button.setAttribute("aria-expanded", "false");

  const score = call.risk_score === null || call.risk_score === undefined ? "–" : String(call.risk_score);
  button.appendChild(makeEl("span", "call-score", score));

  const text = makeEl("span", "call-text");
  const caller = call.caller_number && call.caller_number !== "Unknown" ? call.caller_number : t("calls.unknownCaller");
  text.appendChild(makeEl("span", "call-who", `${caller} ${t("calls.to", { name: call.senior_name })}`));
  const labels = [t(`calls.${call.verdict || "unknown"}`)];
  if (call.alerted) {
    labels.push(t("calls.alerted"));
  }
  if (call.status === "live") {
    labels.push(t("calls.live"));
  }
  text.appendChild(makeEl("span", "call-status", labels.join(" · ")));
  text.appendChild(makeEl("span", "call-time", niceTime(call.started_at)));
  button.appendChild(text);

  const details = makeEl("div", "call-details");
  details.hidden = true;
  button.addEventListener("click", () => {
    details.hidden = !details.hidden;
    button.setAttribute("aria-expanded", String(!details.hidden));
    if (!details.hidden && !details.dataset.loaded) {
      details.dataset.loaded = "yes";
      showDetails(call, details);
    }
  });

  row.append(button, details);
  return row;
}

/**
 * Show the calls that match the current filter.
 *
 * Example: filter "scam"  gives you  only the red and gold calls
 */
function showCalls() {
  const list = document.getElementById("call-list");
  const shown = allCalls.filter((call) => currentFilter === "all" || groupOf(call) === currentFilter);
  list.replaceChildren(...shown.map(callRow));
  const status = document.getElementById("calls-status");
  status.textContent = shown.length === 0 ? t("calls.empty") : "";
  for (const button of document.querySelectorAll("[data-filter]")) {
    const on = button.dataset.filter === currentFilter;
    button.classList.toggle("button-outline", !on);
    button.setAttribute("aria-pressed", String(on));
  }
}

/**
 * Load every call for every senior this family protects, newest first.
 *
 * Example: Ana protects Rosa and Toni  gives you  both of their calls in one list
 */
async function loadCalls() {
  const { ok, data } = await askServer("/api/family");
  if (!ok) {
    document.getElementById("calls-status").textContent = t("calls.error");
    return;
  }
  allCalls = [];
  for (const senior of data.seniors || []) {
    for (const call of senior.calls || []) {
      allCalls.push({ ...call, senior_name: senior.senior_name });
    }
  }
  allCalls.sort((a, b) => String(b.started_at).localeCompare(String(a.started_at)));
  showStats();
  showCalls();
}

/**
 * Start the page: check the login, wire up the filters, load the calls,
 * and check again every 15 seconds so a live call shows up on its own.
 */
async function startCallLog() {
  await requireLogin();
  document.getElementById("calls-page").hidden = false;
  for (const button of document.querySelectorAll("[data-filter]")) {
    button.addEventListener("click", () => {
      currentFilter = button.dataset.filter;
      showCalls();
    });
  }
  await loadCalls();
  setInterval(loadCalls, 15000);
}

// Show it again in the new language when they flip the switch.
document.addEventListener("language-switched", showCalls);

startCallLog();
