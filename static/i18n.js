/*
  i18n.js — Shows every page in English or Spanish, and remembers the choice.

  ("i18n" is short for "internationalization": there are 18 letters between
  the i and the n.)

  How it fits in: every page loads strings.js (all the words), then this
  file, then its own scripts. This file:
    - picks the language: the one they chose before, or else their browser's
    - fills in every element with a data-text="key" attribute, and
      data-text-aria-label="key" for words only screen readers hear
    - shows only the blocks for this language, for longer text with links
      and bold words in it: <div data-lang="en"> and <div data-lang="es" hidden>
    - gives our scripts t("key"), the words for that key in this language
    - makes the English | Español switch, and remembers the choice in the
      browser. Pages that build words themselves listen for the
      "language-switched" event and build them again.
*/

// Where the browser remembers the choice (it stays after closing the page).
const LANGUAGE_KEY = "scam-shield-language";
const LANGUAGES = ["en", "es"];

/**
 * Work out which language to start in: the one they picked last time, or
 * Spanish if their browser is set to Spanish, or else English.
 *
 * Output: "en" or "es"
 * Example: a phone set to Spanish, on the first visit  gives you  "es"
 */
function startingLanguage() {
  try {
    const saved = window.localStorage.getItem(LANGUAGE_KEY);
    if (LANGUAGES.includes(saved)) {
      return saved;
    }
  } catch (error) {
    // Some private windows block storage. Then we just don't remember.
  }
  const browser = (navigator.language || "en").slice(0, 2).toLowerCase();
  return LANGUAGES.includes(browser) ? browser : "en";
}

let currentLanguage = startingLanguage();

/**
 * Get the words for a key in the current language, with the blanks filled in.
 * If a key is missing in Spanish we fall back to English, and if it's
 * missing everywhere we show the key, so it's easy to spot and fix.
 *
 * Input:  key — like "join.mayBeTalking"; details — the blanks, like {name: "Rosa"}
 * Output: the words
 * Example: t("join.mayBeTalking", {name: "Rosa"})  gives you
 *          "Rosa may be talking to a scammer right now." (or the Spanish)
 */
function t(key, details = {}) {
  const words = STRINGS[currentLanguage][key] ?? STRINGS.en[key] ?? key;
  return words.replace(/\{(\w+)\}/g, (blank, name) => details[name] ?? "");
}

/**
 * Translate a message our server sent (it writes them in English).
 *
 * Input:  text — the server's message
 * Output: the Spanish, if we're in Spanish and know it; otherwise the same text
 * Example: in Spanish, translateServerMessage("This call has already ended.")
 *          gives you  "Esta llamada ya terminó."
 */
function translateServerMessage(text) {
  if (currentLanguage === "es" && SERVER_MESSAGES_ES[text]) {
    return SERVER_MESSAGES_ES[text];
  }
  return text;
}

/**
 * Write a saved time as a short date and time, the way the reader expects.
 *
 * Input:  text — like "2026-10-21T18:04:05+00:00"
 * Output: like "Oct 21, 2026, 2:04 PM", or "21 oct 2026, 2:04 p. m." in Spanish
 * Example: formatWhen("2026-10-21T18:04:05+00:00")
 */
function formatWhen(text) {
  return new Date(text).toLocaleString(currentLanguage, { dateStyle: "medium", timeStyle: "short" });
}

/**
 * Put words from strings.js on the page in a way that follows the language
 * switch: the key is kept on the element (data-text), so translatePage()
 * changes it too. Words with blanks filled in can't be kept that way, so
 * the page's script writes those again when the language changes.
 *
 * Input:  element; key — like "demo.waiting"; details — the blanks, if any
 * Example: setText(byId("call-status"), "demo.waiting")  gives you  "Waiting",
 *          and "Esperando" after switching to Spanish
 */
function setText(element, key, details) {
  element.textContent = t(key, details);
  if (details === undefined) {
    element.dataset.text = key;
  } else {
    delete element.dataset.text;
  }
}

/**
 * Put words on the page that aren't ours to translate (like what the AI
 * said), so the language switch leaves them alone.
 *
 * Example: setPlainText(byId("claimed"), "grandson Danny")
 */
function setPlainText(element, text) {
  element.textContent = text;
  delete element.dataset.text;
}

/**
 * Fill in every element on the page that has a data-text key, show only the
 * data-lang blocks for this language, and set the page's own language tag
 * (so screen readers use the right voice).
 *
 * Example: in Spanish, <h1 data-text="dash.title"> becomes "Panel de la familia"
 */
function translatePage() {
  document.documentElement.lang = currentLanguage;
  for (const element of document.querySelectorAll("[data-text]")) {
    element.textContent = t(element.dataset.text);
  }
  for (const block of document.querySelectorAll("[data-lang]")) {
    block.hidden = block.dataset.lang !== currentLanguage;
  }
  for (const element of document.querySelectorAll("[data-text-aria-label]")) {
    element.setAttribute("aria-label", t(element.dataset.textAriaLabel));
  }
  for (const button of document.querySelectorAll(".language-switch")) {
    button.textContent = t("switch.label");
    button.setAttribute("aria-label", t("switch.aria"));
    button.lang = currentLanguage === "en" ? "es" : "en";
  }
}

/**
 * Switch to a language: remember it, translate the page, and tell the page's
 * scripts so they can rebuild the words they made themselves.
 *
 * Input:  language — "en" or "es"
 * Example: setLanguage("es")  gives you  the whole page in Spanish, and
 *          Spanish again next time they visit
 */
function setLanguage(language) {
  currentLanguage = language;
  try {
    window.localStorage.setItem(LANGUAGE_KEY, language);
  } catch (error) {
    // Can't remember it in this browser. The page still switches.
  }
  translatePage();
  document.dispatchEvent(new Event("language-switched"));
}

/**
 * Make the English | Español switch. It shows the OTHER language, written in
 * that language, so a Spanish reader can find "Español" on an English page.
 *
 * Output: the button
 * Example: on an English page  gives you  a button that says "Español"
 */
function languageSwitch() {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "language-switch";
  button.addEventListener("click", () => setLanguage(currentLanguage === "en" ? "es" : "en"));
  return button;
}

/**
 * Put a switch in every spot marked with class "language-switch-spot" (pages
 * without the header have one), then translate the page.
 */
function startTranslating() {
  for (const spot of document.querySelectorAll(".language-switch-spot")) {
    spot.appendChild(languageSwitch());
  }
  translatePage();
}

startTranslating();
