/*
  demo-walkthroughs.js

  The tabs at the top of the demo page, and the short walkthroughs behind
  them: adding someone, pausing protection, removing someone, and the senior
  turning Scam Shield off herself. The demo page is the only place with
  demos, so this is where you show how all of that works.

  How it fits in: demo.html loads this after demo.js, which runs the "A scam
  call" tab. The walkthroughs don't talk to the server at all. Each one is
  a list of steps (WALKTHROUGHS below), and each step adds what Ana sees on
  her phone, what Rosa hears and does on hers, and one line saying what's
  happening. The words are copied from the real app (strings.js and
  app/languages.py), so if those change, change them here too.

  Every phone number here ends in 555-01XX, which is saved for fiction.
*/

// How long Play waits between steps (milliseconds), so there's time to read.
const STEP_PAUSE_MS = 2600;

// The pretend family and numbers, the same people as the scam call demo.
const ROSA_PHONE = "(305) 555-0100";
const SCAM_SHIELD_PHONE = "(305) 555-0150";

/*
  Each walkthrough has a title, a short lead, and its steps. A step has:
    note   — what's happening, in one line (the middle column)
    ana    — what shows up on Ana's phone: a dashboard "screen" or a "text"
    rosa   — what shows up on Rosa's phone: Scam Shield "says", Rosa
             "presses" a key or "dials", or an "info" line
    status — the line at the top of Rosa's phone (optional)
*/
const WALKTHROUGHS = {
  add: {
    title: "Add someone to protect.",
    lead:
      "Ana wants Scam Shield on her mom Rosa's phone. Nothing is listened to until Rosa says YES on her own phone.",
    steps: [
      {
        note: "Ana fills in Rosa's name and number on her dashboard.",
        ana: [
          {
            kind: "screen",
            title: "Protect someone's calls",
            lines: ["Their name: Rosa", `Their phone: ${ROSA_PHONE}`, "Cell phone · English"],
            buttons: [{ text: "Ask them for their OK", style: "primary" }],
          },
        ],
      },
      {
        note: "Scam Shield calls Rosa to ask for her OK.",
        status: "Scam Shield is calling",
        ana: [{ kind: "screen", title: "Setting up Scam Shield for Rosa", lines: ["We're calling them now. Waiting for them to press 1…"] }],
        rosa: [
          {
            kind: "says",
            body:
              "Hello Rosa. This is Scam Shield. Ana wants to protect your phone calls from scammers. We would listen to your calls, and alert Ana if one sounds like a scam. To allow it, press 1. To say no, press 2.",
          },
        ],
      },
      {
        note: "Rosa presses 1 to say YES.",
        rosa: [
          { kind: "presses", body: "1" },
          { kind: "says", body: "Thank you. Scam Shield is now on. Ana will finish setting it up. Goodbye." },
        ],
        status: "Call ended",
      },
      {
        note: "Ana gets a text, and her dashboard says Rosa is protected.",
        ana: [
          { kind: "text", body: "Scam Shield: Rosa said YES. Their calls are now protected." },
          {
            kind: "screen",
            title: "Finish setting up their phone",
            pill: "Protected",
            lines: ["One last thing: a few quick steps on their phone."],
            buttons: [{ text: "Show me the steps", style: "primary" }],
          },
        ],
      },
      {
        note: "Ana sets up Rosa's phone in 2 steps: open the Scam Shield app, then send calls through Scam Shield.",
        ana: [
          {
            kind: "screen",
            title: "Set up Rosa's phone",
            lines: ["1. Turn on the Scam Shield app", "2. Send their calls to Scam Shield:"],
            code: "**21*+13055550150#",
          },
        ],
        rosa: [
          { kind: "info", body: "Rosa's Scam Shield phone. Ready. Calls will ring here." },
          { kind: "dials", body: "**21*+13055550150#" },
        ],
        status: "Protected",
      },
    ],
  },

  pause: {
    title: "Pause protection for a while.",
    lead:
      "Rosa is having friends over and doesn't want Scam Shield listening today. Ana can pause it and turn it back on with one tap.",
    steps: [
      {
        note: "Rosa is protected. Ana sees her on the dashboard.",
        status: "Protected",
        ana: [
          {
            kind: "screen",
            title: "Rosa",
            pill: "Protected",
            lines: ["Alerts go to Ana."],
            buttons: [{ text: "Pause protection", style: "secondary" }],
          },
        ],
      },
      {
        note: "Ana taps Pause protection.",
        status: "Paused",
        ana: [
          {
            kind: "screen",
            title: "Rosa",
            pill: "Paused",
            lines: ["Protection is paused. Rosa's calls ring like normal, and we aren't listening."],
            buttons: [{ text: "Turn protection back on", style: "primary" }],
          },
        ],
        rosa: [{ kind: "info", body: "Calls ring like normal. Scam Shield isn't listening." }],
      },
      {
        note: "Later, Ana taps Turn protection back on.",
        status: "Protected",
        ana: [
          {
            kind: "screen",
            title: "Rosa",
            pill: "Protected",
            lines: ["Alerts go to Ana."],
            buttons: [{ text: "Pause protection", style: "secondary" }],
          },
        ],
        rosa: [{ kind: "info", body: "Scam Shield is listening for scams again." }],
      },
    ],
  },

  remove: {
    title: "Remove someone.",
    lead: "Ana doesn't need Scam Shield on Rosa's phone anymore. She removes her from the dashboard.",
    steps: [
      {
        note: "Ana taps Remove on Rosa's card.",
        status: "Protected",
        ana: [
          {
            kind: "screen",
            title: "Rosa",
            pill: "Protected",
            lines: ["Alerts go to Ana."],
            buttons: [{ text: "Remove", style: "danger" }],
          },
        ],
      },
      {
        note: "The dashboard asks if she's sure, right on the card.",
        ana: [
          {
            kind: "screen",
            title: "Rosa",
            lines: [
              "Are you sure you want to remove Rosa? This deletes them and all their calls, and Scam Shield stops protecting them. It can't be undone.",
            ],
            buttons: [
              { text: "Yes, remove", style: "danger" },
              { text: "Keep them", style: "secondary" },
            ],
          },
        ],
      },
      {
        note: "Ana taps Yes, remove. Scam Shield stops listening right away, and Rosa's calls still ring.",
        status: "Not protected",
        ana: [
          {
            kind: "screen",
            title: "Your family",
            lines: [
              "Rosa was removed, and Scam Shield isn't listening. Their calls still ring like normal. To stop their calls going through Scam Shield at all, turn off call forwarding on their phone: dial ##21# (Verizon: *73).",
            ],
          },
        ],
        rosa: [{ kind: "info", body: "Scam Shield isn't listening. Calls still ring like normal." }],
      },
      {
        note: "On Rosa's phone, Ana dials ##21# to turn off call forwarding. Now calls go straight to Rosa.",
        status: "Calls ring like normal",
        rosa: [
          { kind: "dials", body: "##21#" },
          { kind: "info", body: "Call forwarding is off." },
        ],
      },
    ],
  },

  optout: {
    title: "Rosa turns it off herself.",
    lead:
      "It's Rosa's phone, so Rosa is always in charge. She can turn Scam Shield off any time with one call, without asking Ana.",
    steps: [
      {
        note: "Rosa calls the Scam Shield number from her own phone.",
        status: `Calling ${SCAM_SHIELD_PHONE}`,
        ana: [{ kind: "screen", title: "Rosa", pill: "Protected", lines: ["Alerts go to Ana."] }],
        rosa: [
          { kind: "dials", body: SCAM_SHIELD_PHONE },
          {
            kind: "says",
            body:
              "Hello Rosa. This is Scam Shield. Ana set up Scam Shield to listen to your calls and warn them about scams. If you want to cancel Scam Shield from listening to your conversations, press 2. To keep it on, press 1.",
          },
        ],
      },
      {
        note: "Rosa presses 2. Scam Shield stops listening right away.",
        status: "Call ended",
        rosa: [
          { kind: "presses", body: "2" },
          {
            kind: "says",
            body: "Scam Shield is now canceled. We will not listen to your calls anymore. We let Ana know. Goodbye.",
          },
        ],
      },
      {
        note: "Ana gets a text, and Rosa's card says Turned off.",
        status: "Not protected",
        ana: [
          { kind: "text", body: "Scam Shield: Rosa turned Scam Shield off. We stopped watching their calls." },
          { kind: "screen", title: "Rosa", pill: "Turned off", lines: ["They turned Scam Shield off."] },
        ],
      },
    ],
  },
};

// What we remember while the page is open.
const flow = {
  scene: "call",   // which tab is showing: "call" (demo.js) or a WALKTHROUGHS key
  nextStep: 0,     // which step of the walkthrough comes next
  playing: false,  // true while Play is running
  run: 0,          // goes up on every Play and Start over, so an old Play stops
};

/**
 * Make an element with a class and some text. The text is always plain
 * text, never HTML.
 *
 * Example: makeFlowTag("p", "note", "Hi")  gives you  <p class="note">Hi</p>
 */
function makeFlowTag(tag, className = "", text = "") {
  const element = document.createElement(tag);
  if (className) {
    element.className = className;
  }
  element.textContent = text;
  return element;
}

/**
 * One thing on Ana's phone: a dashboard screen or a text she got.
 *
 * Input:  item — {kind: "screen", title, pill, lines, buttons, code} or {kind: "text", body}
 * Output: the <li>
 * Example: {kind: "text", body: "Scam Shield: Rosa said YES..."}  gives you  a text bubble
 */
function anaItem(item) {
  if (item.kind === "text") {
    const text = makeFlowTag("li");
    text.append(makeFlowTag("span", "flow-who", "Text from Scam Shield"), item.body);
    return text;
  }

  const screen = makeFlowTag("li", "flow-screen");
  const top = makeFlowTag("div", "flow-screen-top");
  top.appendChild(makeFlowTag("p", "flow-screen-title", item.title));
  if (item.pill) {
    top.appendChild(makeFlowTag("span", "flow-pill", item.pill));
  }
  screen.appendChild(top);
  for (const line of item.lines || []) {
    screen.appendChild(makeFlowTag("p", "", line));
  }
  if (item.code) {
    screen.appendChild(makeFlowTag("p", "flow-code", item.code));
  }
  if (item.buttons) {
    // These only show what Ana taps. Next step does the tapping.
    const buttons = makeFlowTag("div", "flow-buttons");
    for (const button of item.buttons) {
      buttons.appendChild(makeFlowTag("span", `flow-button ${button.style}`, button.text));
    }
    screen.appendChild(buttons);
  }
  return screen;
}

/**
 * One thing on Rosa's phone: what Scam Shield says, a key she presses, a
 * number she dials, or a short line about her phone.
 *
 * Example: {kind: "presses", body: "1"}  gives you  "Rosa presses 1" on her side
 */
function rosaItem(item) {
  if (item.kind === "info") {
    return makeFlowTag("li", "ended", item.body);
  }
  const fromRosa = item.kind === "presses" || item.kind === "dials";
  const line = makeFlowTag("li", fromRosa ? "senior" : "caller");
  const who = { says: "Scam Shield", presses: "Rosa presses", dials: "Rosa dials" }[item.kind];
  line.appendChild(makeFlowTag("span", "who", who));
  line.appendChild(makeFlowTag("span", fromRosa ? "flow-code" : "", item.body));
  return line;
}

/**
 * Add something to one phone's list and scroll so it's showing.
 *
 * Example: addToFeed("flow-ana", element)  gives you  the element at the bottom of Ana's phone
 */
function addToFeed(listId, element) {
  const list = byId(listId);
  list.querySelector(".empty")?.remove();
  list.appendChild(element);
  list.scrollTop = list.scrollHeight;
}

/**
 * Show the next step of the walkthrough on both phones, and mark it in the
 * middle column.
 *
 * Output: true if there are more steps after this one
 * Example: in "Add someone", the 3rd tap shows Rosa pressing 1
 */
function showNextStep() {
  const walkthrough = WALKTHROUGHS[flow.scene];
  const current = walkthrough.steps[flow.nextStep];
  if (!current) {
    return false;
  }
  for (const item of current.ana || []) {
    addToFeed("flow-ana", anaItem(item));
  }
  for (const item of current.rosa || []) {
    addToFeed("flow-rosa", rosaItem(item));
  }
  if (current.status) {
    byId("flow-rosa-status").textContent = current.status;
  }

  const notes = byId("flow-notes").children;
  for (let index = 0; index < notes.length; index++) {
    notes[index].className = index < flow.nextStep ? "done" : index === flow.nextStep ? "now" : "";
  }
  flow.nextStep += 1;
  updateFlowButtons();
  return flow.nextStep < walkthrough.steps.length;
}

/**
 * Plays the whole walkthrough, one step at a time. Press it again to pause.
 *
 * Example: Play on "Remove someone" shows all 4 steps, a few seconds apart
 */
async function playFlow() {
  if (flow.playing) {
    flow.playing = false;
    updateFlowButtons();
    return;
  }
  const run = ++flow.run;
  flow.playing = true;
  updateFlowButtons();
  while (flow.playing && flow.run === run) {
    if (!showNextStep()) {
      break;
    }
    await wait(STEP_PAUSE_MS);
  }
  // Only stop if nobody pressed Start over or switched tabs in the meantime.
  if (flow.run === run) {
    flow.playing = false;
    updateFlowButtons();
  }
}

/**
 * Clear both phones and list the steps, ready to start the walkthrough.
 *
 * Example: Start over  gives you  empty phones and every step waiting in the middle
 */
function resetFlow() {
  const walkthrough = WALKTHROUGHS[flow.scene];
  flow.run += 1;
  flow.nextStep = 0;
  flow.playing = false;
  byId("flow-title").textContent = walkthrough.title;
  byId("flow-lead").textContent = walkthrough.lead;
  byId("flow-rosa-status").textContent = "Waiting";
  byId("flow-ana").replaceChildren(makeFlowTag("li", "empty", "Press Play or Next step to start."));
  byId("flow-rosa").replaceChildren();
  byId("flow-notes").replaceChildren(...walkthrough.steps.map((step) => makeFlowTag("li", "", step.note)));
  updateFlowButtons();
}

/**
 * Keep the buttons matching what's happening.
 *
 * Example: at the last step, Next step turns off
 */
function updateFlowButtons() {
  const walkthrough = WALKTHROUGHS[flow.scene];
  const done = !walkthrough || flow.nextStep >= walkthrough.steps.length;
  byId("flow-play").querySelector("span").textContent = flow.playing ? "Pause" : "Play";
  byId("flow-play").disabled = done && !flow.playing;
  byId("flow-step").disabled = flow.playing || done;
}

/**
 * Switch to one of the demos, from the tabs or the #part of the address.
 *
 * Input:  scene — "call" for the scam call, or a WALKTHROUGHS key like "add"
 * Example: showScene("remove")  gives you  the "Remove someone" walkthrough
 */
function showScene(scene) {
  if (scene !== "call" && !WALKTHROUGHS[scene]) {
    scene = "call";
  }
  flow.scene = scene;
  const isCall = scene === "call";
  for (const tab of document.querySelectorAll(".scene-tab")) {
    tab.setAttribute("aria-selected", String(tab.dataset.scene === scene));
  }
  byId("call-intro").hidden = !isCall;
  byId("call-stage").hidden = !isCall;
  byId("flow-intro").hidden = isCall;
  byId("flow-stage").hidden = isCall;

  if (isCall) {
    flow.run += 1;
    flow.playing = false;
  } else {
    // Leaving the scam call: stop it playing and talking (demo.js).
    if (state.playing) {
      play();
    }
    window.speechSynthesis?.cancel();
    resetFlow();
  }
}

for (const tab of document.querySelectorAll(".scene-tab")) {
  tab.addEventListener("click", () => {
    // Put it in the address too, so the link can be shared (/demo#add).
    history.replaceState(null, "", tab.dataset.scene === "call" ? "/demo" : `#${tab.dataset.scene}`);
    showScene(tab.dataset.scene);
  });
}
byId("flow-play").addEventListener("click", playFlow);
byId("flow-step").addEventListener("click", showNextStep);
byId("flow-restart").addEventListener("click", resetFlow);
window.addEventListener("hashchange", () => showScene(window.location.hash.slice(1)));

showScene(window.location.hash.slice(1) || "call");
