/*
  forgot.js — The "Forgot your password?" link on the login page.

  How it fits in: login.js logs people in and signs them up. This file asks
  Supabase (auth.js) to email a reset link. The link brings them back to the
  Account page (/profile?reset=1) already logged in, where account.js lets
  them choose a new password.
*/

/**
 * Email a reset link to whatever is in the Email box.
 *
 * Example: ana@example.com in the box  gives you  "Check your email for a link..."
 */
async function sendResetLink() {
  const email = document.querySelector("#login-form input[name=email]").value.trim();
  const error = document.getElementById("login-error");
  const message = document.getElementById("login-message");
  error.textContent = "";
  message.textContent = "";
  if (!email) {
    error.textContent = t("account.needEmail");
    return;
  }

  const client = await getAuthClient();
  if (client === null) {
    return;
  }
  const { error: problem } = await client.auth.resetPasswordForEmail(email, {
    redirectTo: `${window.location.origin}/profile?reset=1`,
  });
  // We say the same thing either way, so nobody can use this to check which
  // emails have an account.
  if (problem && problem.status === 429) {
    error.textContent = t("account.sendFailed");
    return;
  }
  message.textContent = t("account.sent");
}

document.getElementById("forgot-button").addEventListener("click", sendResetLink);
