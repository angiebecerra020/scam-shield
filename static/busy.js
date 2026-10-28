/*
  busy.js — Small helpers so a page never looks frozen or broken.

  How it fits in: every page loads this file after i18n.js (for the words)
  and before its own script. It gives them:
    - setBusy() and setReady(): while we wait on the server (which waits on
      Twilio, Supabase, Nemotron or Tavily), the button says what's happening,
      like "Sending the text…", and can't be tapped twice
    - fetchJson(): asks our server for something and ALWAYS comes back with
      {ok, data}, even when the internet is down or the server breaks. When
      something goes wrong, data.error holds a message in plain words, in
      the reader's language.
*/

/**
 * Turn a button off and change its words while we wait, so it can't be
 * tapped twice and the person can see something is happening.
 *
 * Input:  button — the button; busyText — what to say while we wait
 * Output: nothing. Call setReady(button) when the wait is over.
 * Example: setBusy(button, "Calling your phone…")
 */
function setBusy(button, busyText) {
  // Remember the button's words the first time, so setReady() can put them back.
  if (button.dataset.readyText === undefined) {
    button.dataset.readyText = button.textContent;
  }
  button.disabled = true;
  button.textContent = busyText;
  // Tells screen readers the button is working on something.
  button.setAttribute("aria-busy", "true");
}

/**
 * Turn a button back on with its usual words, after setBusy().
 *
 * Input:  button — the button
 * Output: nothing
 * Example: setReady(button)  gives you  "Call me into the call" again
 */
function setReady(button) {
  if (button.dataset.readyText !== undefined) {
    button.textContent = button.dataset.readyText;
    delete button.dataset.readyText;
  }
  button.disabled = false;
  button.removeAttribute("aria-busy");
}

/**
 * Ask our server for something and read the JSON answer, without ever
 * throwing. That way one dropped connection can't freeze the page.
 *
 * Input:  url, options — the same as fetch()
 * Output: {ok, status, data}. ok is true for a successful answer. When it
 *         isn't, data.error is a message we can show as it is, already in
 *         the reader's language.
 * Examples:
 *   await fetchJson("/api/join/Xy7")  gives you  {ok: true, status: 200, data: {senior_name: "Rosa", ...}}
 *   with the Wi-Fi off  gives you  {ok: false, status: 0, data: {error: "We couldn't reach Scam Shield..."}}
 */
async function fetchJson(url, options = {}) {
  let response;
  try {
    response = await fetch(url, options);
  } catch (problem) {
    // fetch only throws when it couldn't reach the server at all.
    return { ok: false, status: 0, data: { error: t("error.offline") } };
  }

  let data = {};
  try {
    data = await response.json();
  } catch (problem) {
    // Some answers (like a crashed server's error page) aren't JSON. That's fine.
  }

  if (!response.ok && !data.error) {
    data.error = t("error.server");
    // FastAPI says what's wrong with a form in "detail". A plain string is
    // already written for people (like "Please log in first.").
    if (typeof data.detail === "string") {
      data.error = data.detail;
    } else if (response.status === 422) {
      data.error = t("error.form");
    }
  }
  // Our server writes its messages in English. Show them in Spanish if we can.
  if (data.error) {
    data.error = translateServerMessage(data.error);
  }
  return { ok: response.ok, status: response.status, data };
}
