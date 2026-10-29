/*
  setup.js — Fills in the setup page (setup.html) for one senior.

  How it fits in: setup.html loads this after auth.js and busy.js. It:
    - checks the family member is logged in (or sends them to /login)
    - reads the senior's ID from the address (/setup/<id>)
    - asks our server for their setup details (GET /api/enrollments/{id})
    - shows the steps for a cell phone (2 steps) or a landline (3 steps),
      with the codes to dial in big letters

  The words come from strings.js, in English or Spanish (see i18n.js). When
  the language changes, we draw the steps again.
*/

// The senior we got from the server, so we can redraw in a new language.
let enrollment = null;
// Or, if we couldn't get them, the key for what went wrong (in strings.js).
let problemKey = "";

/**
 * Make an element with a class and some text.
 *
 * Input:  tag, className, text (both optional)
 * Output: the new element
 * Example: makeTag("p", "hint", "Hi")  gives you  <p class="hint">Hi</p>
 */
function makeTag(tag, className = "", text = "") {
  const element = document.createElement(tag);
  if (className) {
    element.className = className;
  }
  element.textContent = text;
  return element;
}

/**
 * A code to dial (or type), in big letters so it's easy to copy by eye.
 *
 * Example: dialCode("**21*+15555550150#")  gives you  <p class="dial-code">**21*+15555550150#</p>
 */
function dialCode(code) {
  return makeTag("p", "dial-code", code);
}

/**
 * One numbered step: a short title, then its lines.
 *
 * Input:  title — the step's title
 *         parts — the elements under the title, in order
 * Output: the <li>
 * Example: step("Send their calls to Scam Shield", [makeTag("p", "", "Dial this:"), dialCode("*72...")])
 */
function step(title, parts) {
  const item = document.createElement("li");
  item.appendChild(makeTag("h2", "", title));
  item.append(...parts);
  return item;
}

/**
 * A "Copy link" button, for when the family has the link on their own phone
 * and needs to get it onto the senior's.
 *
 * Example: tap "Copy link"  gives you  the link copied, and the button says "Copied"
 */
function copyButton(link) {
  const button = makeTag("button", "button-small button-outline", t("setup.copyLink"));
  button.type = "button";
  button.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(link);
      button.textContent = t("setup.copied");
    } catch (problem) {
      // Some browsers block copying. The link is right there to tap or hold.
      button.textContent = t("setup.cantCopy");
    }
  });
  return button;
}

/**
 * The 2 steps for a cell phone: turn on our calling app, then forward calls.
 *
 * Input:  name, setup (from the server), number (the Scam Shield number)
 * Output: the <li> steps
 */
function cellSteps(name, setup, number) {
  const link = makeTag("a", "setup-link", setup.app_link);
  link.href = setup.app_link;
  link.target = "_blank";

  return [
    step(t("setup.cellStep1Title"), [
      makeTag("p", "", t("setup.cellStep1a", { name })),
      link,
      copyButton(setup.app_link),
      makeTag("p", "", t("setup.cellStep1b", { button: t("phone.turnOn") })),
      makeTag("p", "hint", t("setup.cellStep1c")),
    ]),
    step(t("setup.cellStep2Title"), [
      makeTag("p", "", t("setup.cellStep2a")),
      dialCode(`**21*${number}#`),
      makeTag("p", "hint", t("setup.verizon")),
      dialCode(`*72${number}`),
    ]),
  ];
}

/**
 * The 3 steps for a landline: set up the adapter, forward calls, move the
 * phone over to the adapter.
 *
 * Input:  name, setup (from the server), number (the Scam Shield number)
 * Output: the <li> steps
 */
function landlineSteps(name, setup, number) {
  const signIn = makeTag("dl", "setup-details");
  signIn.append(
    makeTag("dt", "", t("setup.username")),
    makeTag("dd", "", setup.adapter_username),
    makeTag("dt", "", t("setup.domain")),
    makeTag("dd", "", setup.adapter_domain || t("setup.yourDomain"))
  );

  return [
    step(t("setup.landStep1Title"), [makeTag("p", "", t("setup.landStep1a")), signIn]),
    step(t("setup.landStep2Title"), [
      makeTag("p", "", t("setup.landStep2a", { name })),
      dialCode(`*72${number}`),
      makeTag("p", "", t("setup.landStep2b")),
    ]),
    step(t("setup.landStep3Title"), [makeTag("p", "", t("setup.landStep3a", { name }))]),
  ];
}

/**
 * Draw the page for the senior we got from the server.
 *
 * Example: Rosa, cell phone, said YES  gives you  "Set up Rosa's phone" and 2 steps
 *          Rosa hasn't pressed 1 yet  gives you  "Rosa hasn't said YES yet..."
 */
function drawSetup() {
  const name = enrollment.senior_name;
  document.getElementById("setup-title").textContent = t("setup.title", { name });
  const message = document.getElementById("setup-message");
  const steps = document.getElementById("setup-steps");
  const off = document.getElementById("setup-off");

  // Paused seniors already said YES, so they can still see their steps.
  const saidYes = enrollment.status === "active" || enrollment.status === "paused";
  steps.hidden = !saidYes;
  off.hidden = !saidYes;
  if (!saidYes) {
    message.textContent = t("setup.notYet", { name });
    return;
  }

  const setup = enrollment.setup;
  const number = setup.forward_to || t("setup.yourNumber");
  const landline = enrollment.phone_type === "landline";
  message.textContent = t(landline ? "setup.landlineIntro" : "setup.cellIntro", { name });
  steps.replaceChildren(...(landline ? landlineSteps(name, setup, number) : cellSteps(name, setup, number)));
  document.getElementById("setup-off-text").textContent = t(landline ? "setup.landlineOff" : "setup.cellOff");
}

/**
 * Check the login, then load the senior from the address and draw the steps.
 *
 * Example: open /setup/abc  gives you  the steps for senior "abc"
 */
async function startSetupPage() {
  document.getElementById("setup-message").textContent = t("setup.loading");
  const { loginOn, user } = await requireLogin();
  if (loginOn && user === null) {
    // requireLogin() is already sending them to /login.
    return;
  }

  // "/setup/abc" gives you "abc"
  const enrollmentId = decodeURIComponent(window.location.pathname.split("/").pop());
  const { ok, status, data } = await fetchJson(`/api/enrollments/${encodeURIComponent(enrollmentId)}`, {
    headers: await loginHeaders(),
  });
  if (status === 401) {
    // The login ran out. Back to /login.
    window.location.replace("/login");
    return;
  }
  const message = document.getElementById("setup-message");
  if (status === 404) {
    problemKey = "setup.notFound";
    message.textContent = t(problemKey);
    return;
  }
  if (!ok) {
    // Already in their language (fetchJson in busy.js).
    message.textContent = data.error;
    return;
  }
  enrollment = data;
  drawSetup();
}

// When they flip the language switch, draw the steps again in that language.
document.addEventListener("language-switched", () => {
  if (enrollment !== null) {
    drawSetup();
  } else if (problemKey) {
    document.getElementById("setup-message").textContent = t(problemKey);
  }
});

startSetupPage();
