/*
  profile.js — Makes the profile page (profile.html) work.

  How it fits in: profile.html loads this after auth.js and busy.js. It:
    - checks the family member is logged in (or sends them to /login)
    - fills the form with their saved details (GET /api/profile)
    - saves the form (PUT /api/profile). The server also copies the new
      details onto every senior they protect (app/profile.py)

  The words come from strings.js, in English or Spanish (see i18n.js).
*/

// What the last save did ("profile.saved"), so we can redraw it in a new language.
let savedKey = "";

/**
 * Send a request with the login token, and read the JSON answer.
 * If the login ran out, it sends them back to /login.
 *
 * Input:  url, options — the same as fetch()
 * Output: {ok, data}, the same as fetchJson() in busy.js
 * Example: await profileRequest("/api/profile")
 *          gives you {ok: true, data: {profile: {name: "Ana", ...}}}
 */
async function profileRequest(url, options = {}) {
  let headers = { ...options.headers };
  try {
    headers = { ...headers, ...(await loginHeaders()) };
  } catch (error) {
    return { ok: false, data: { error: t("error.offline") } };
  }
  const { ok, status, data } = await fetchJson(url, { ...options, headers });
  if (status === 401) {
    window.location.replace("/login");
  }
  return { ok, data };
}

/**
 * Put saved details into the form.
 *
 * Input:  profile — {name, phone, email, language} from the server
 * Example: fillForm({name: "Ana", phone: "+13055550101", ...})
 *          gives you "Ana" in Your name and "305-555-0101" in Your phone
 */
function fillForm(profile) {
  // form.elements, because form.name is the form's own name, not the box.
  const boxes = document.getElementById("profile-form").elements;
  boxes.name.value = profile.name;
  boxes.phone.value = showPhone(profile.phone);
  boxes.email.value = profile.email || "";
  boxes.language.value = profile.language;
}

/**
 * Write a saved US number the way people type it.
 *
 * Example: showPhone("+13055550101")  gives you  "305-555-0101"
 *          showPhone("+442079460958")  gives you  "+442079460958" (not a US number)
 */
function showPhone(phone) {
  const us = /^\+1(\d{3})(\d{3})(\d{4})$/.exec(phone);
  return us ? `${us[1]}-${us[2]}-${us[3]}` : phone;
}

/**
 * Save the form.
 *
 * Input:  event — the form's submit event
 * Example: change Your phone and tap Save  gives you  "Saved."
 */
async function saveProfile(event) {
  event.preventDefault();
  const form = event.target;
  const savedElement = document.getElementById("profile-saved");
  const errorElement = document.getElementById("profile-error");
  savedKey = "";
  savedElement.textContent = "";
  errorElement.textContent = "";

  const button = form.querySelector('button[type="submit"]');
  setBusy(button, t("profile.busySave"));
  const { ok, data } = await profileRequest("/api/profile", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(Object.fromEntries(new FormData(form))),
  });
  setReady(button);

  if (!ok) {
    errorElement.textContent = data.error;
    return;
  }
  fillForm(data.profile);
  savedKey = "profile.saved";
  savedElement.textContent = t(savedKey);
}

/**
 * Check the login, then show the page with their saved details.
 *
 * Example: Ana opens /profile  gives you  the form with her name and phone in it
 */
async function startProfilePage() {
  let login;
  try {
    login = await requireLogin();
  } catch (error) {
    document.body.textContent = t("error.refresh");
    return;
  }
  if (login.loginOn && login.user === null) {
    return; // requireLogin() is already taking them to /login
  }
  document.getElementById("profile-page").hidden = false;

  const { ok, data } = await profileRequest("/api/profile");
  if (!ok) {
    document.getElementById("profile-error").textContent = data.error;
  } else if (data.profile !== null) {
    fillForm(data.profile);
  }
}

document.getElementById("profile-form").addEventListener("submit", saveProfile);
// When they flip the language switch, redraw "Saved." in that language.
document.addEventListener("language-switched", () => {
  if (savedKey) {
    document.getElementById("profile-saved").textContent = t(savedKey);
  }
});

startProfilePage();
