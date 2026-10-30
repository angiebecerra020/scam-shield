/*
  account.js — The "Your login" part of the Account page (profile.html).

  How it fits in: profile.js handles who gets the alerts (name, phone,
  email). This file handles the login itself: it shows the email they log in
  with, and lets them pick a new password with Supabase (auth.js). When they
  come back from a "Forgot your password?" email, the link opens this page
  with ?reset=1, already logged in, so they can set the new one right here.
*/

/**
 * Show the login email, and the "you're back in" note after a reset link.
 *
 * Example: Ana logs in  gives you  "Login email: ana@example.com"
 */
async function showLogin() {
  const client = await getAuthClient();
  if (client === null) {
    return; // Login is turned off, so there's no password to change.
  }
  const session = await getSession();
  if (session === null) {
    return; // profile.js is already sending them to /login.
  }
  document.getElementById("login-email").textContent = session.user.email;
  document.getElementById("login-section").hidden = false;
  if (new URLSearchParams(window.location.search).get("reset") === "1") {
    document.getElementById("reset-note").hidden = false;
    document.getElementById("login-section").scrollIntoView();
  }
}

/**
 * Save the new password, once both boxes match.
 *
 * Example: "sunflower22" twice  gives you  "Your password is changed."
 */
async function changePassword(event) {
  event.preventDefault();
  const form = event.target;
  const error = document.getElementById("password-error");
  const message = document.getElementById("password-message");
  error.textContent = "";
  message.textContent = "";

  const password = form.password.value;
  if (password.length < 8) {
    error.textContent = t("account.tooShort");
    return;
  }
  if (password !== form.confirm.value) {
    error.textContent = t("account.mismatch");
    return;
  }

  const client = await getAuthClient();
  const { error: problem } = await client.auth.updateUser({ password });
  if (problem) {
    error.textContent = t("account.failed");
    return;
  }
  form.reset();
  message.textContent = t("account.changed");
}

document.getElementById("password-form").addEventListener("submit", changePassword);
showLogin();
