/*
  login.js — Makes the login page work.

  How it fits in: login.html loads this after auth.js. It:
    - switches the form between "Log in" and "Sign up"
    - logs the person in, or makes their account, with Supabase
    - sends them to the dashboard once they're in
  If they're already logged in, it skips straight to the dashboard.
*/

// "login" or "signup", whichever tab is picked.
let formMode = "login";

// The words on the page for each tab.
const FORM_TEXT = {
  login: {
    title: "Welcome back",
    hint: "Log in to see the calls you're protecting.",
    button: "Log in",
    // Lets password managers fill in the saved password
    passwordAutocomplete: "current-password",
  },
  signup: {
    title: "Make your account",
    hint: "Free for families. Use at least 6 characters for your password.",
    button: "Sign up",
    // Lets password managers suggest a strong new password
    passwordAutocomplete: "new-password",
  },
};

/**
 * Switch the form to "log in" or "sign up".
 *
 * Input:  mode — "login" or "signup"
 * Output: nothing; it changes the words on the page.
 * Example: setFormMode("signup")  gives you  a "Make your account" form
 */
function setFormMode(mode) {
  formMode = mode;
  const text = FORM_TEXT[mode];
  document.getElementById("login-title").textContent = text.title;
  document.getElementById("login-hint").textContent = text.hint;
  document.getElementById("login-button").textContent = text.button;
  document.querySelector("input[name=password]").autocomplete = text.passwordAutocomplete;
  // aria-pressed tells screen readers which tab is picked
  document.getElementById("tab-login").setAttribute("aria-pressed", mode === "login");
  document.getElementById("tab-signup").setAttribute("aria-pressed", mode === "signup");
  document.getElementById("login-error").textContent = "";
  document.getElementById("login-message").textContent = "";
}

/**
 * Log in or sign up with the email and password in the form.
 *
 * Input:  event — the form's submit event
 * Output: nothing; it goes to the dashboard, or shows what went wrong.
 * Example: right email and password  gives you  the dashboard
 *          a new sign up  gives you  "Check your email..." (if Supabase asks
 *          people to confirm their email first)
 */
async function submitLogin(event) {
  // Stop the browser from reloading the page; we send the form ourselves.
  event.preventDefault();
  const form = event.target;
  const button = document.getElementById("login-button");
  const errorElement = document.getElementById("login-error");
  const messageElement = document.getElementById("login-message");
  errorElement.textContent = "";
  messageElement.textContent = "";

  const email = form.email.value.trim();
  const password = form.password.value;

  // Say what's happening while Supabase checks, and turn the button off so
  // a double tap doesn't send twice (busy.js).
  setBusy(button, formMode === "login" ? "Logging in…" : "Making your account…");
  // Leaving for the dashboard: keep the button busy until the page changes.
  let leaving = false;
  try {
    const client = await getAuthClient();
    if (formMode === "login") {
      const { error } = await client.auth.signInWithPassword({ email, password });
      if (error) {
        errorElement.textContent = friendlyError(error);
        return;
      }
      leaving = true;
      window.location.href = "/dashboard";
      return;
    }

    const { data, error } = await client.auth.signUp({
      email,
      password,
      // Where the "confirm your email" link takes them.
      options: { emailRedirectTo: `${window.location.origin}/dashboard` },
    });
    if (error) {
      errorElement.textContent = friendlyError(error);
      return;
    }
    if (data.session) {
      // Email confirmation is off in Supabase, so they're already logged in.
      leaving = true;
      window.location.href = "/dashboard";
      return;
    }
    messageElement.textContent =
      `Almost done! We sent a link to ${email}. Open it to finish making your account.`;
  } catch (problem) {
    errorElement.textContent = "We couldn't reach the login service. Check your internet and try again.";
  } finally {
    if (!leaving) {
      setReady(button);
    }
  }
}

/**
 * Turn a Supabase error into words a family member understands.
 *
 * Input:  error — the error from supabase-js
 * Output: a short message to show on the page.
 * Example: friendlyError({message: "Invalid login credentials"})
 *          gives you  "That email or password isn't right."
 */
function friendlyError(error) {
  const message = error.message || "";
  if (message.includes("Invalid login credentials")) {
    return "That email or password isn't right.";
  }
  if (message.includes("Email not confirmed")) {
    return "Please open the link we emailed you first, then log in.";
  }
  if (message.includes("already registered")) {
    return "There's already an account with that email. Try logging in.";
  }
  // Anything else: Supabase's own message is clear enough.
  return message || "Something went wrong. Please try again.";
}

/**
 * Get the page ready: skip ahead if they're already logged in, or explain
 * that login is off.
 *
 * Input:  nothing
 * Output: nothing; it updates the page or moves to the dashboard.
 * Example: already logged in  gives you  the dashboard right away
 */
async function startLoginPage() {
  try {
    const client = await getAuthClient();
    if (client === null) {
      document.getElementById("login-form").hidden = true;
      document.querySelector(".tabs").hidden = true;
      document.getElementById("login-off").hidden = false;
      return;
    }
    if ((await getSession()) !== null) {
      window.location.replace("/dashboard");
    }
  } catch (problem) {
    document.getElementById("login-error").textContent =
      "We couldn't reach the server. Please refresh the page.";
  }
}

document.getElementById("tab-login").addEventListener("click", () => setFormMode("login"));
document.getElementById("tab-signup").addEventListener("click", () => setFormMode("signup"));
document.getElementById("login-form").addEventListener("submit", submitLogin);

// Open the Sign up tab when the link says so, e.g. /login?mode=signup
if (new URLSearchParams(window.location.search).get("mode") === "signup") {
  setFormMode("signup");
}
startLoginPage();
