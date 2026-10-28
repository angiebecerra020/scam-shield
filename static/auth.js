/*
  auth.js — Login helpers shared by the login page and the family dashboard.

  How it fits in: login.html and index.html load this file right after the
  Supabase library (supabase-js). Supabase keeps the families' accounts, and
  supabase-js remembers who's logged in, in the browser.

  This file:
    - asks our server how to reach Supabase (GET /api/auth-config)
    - gets the person's access token, so the dashboard can send it with each
      request (the server checks it in app/auth.py)
    - sends people who aren't logged in to /login
    - logs people out

  If the server says login is off (no Supabase settings in .env), these
  helpers let everyone through, so local testing still works.
*/

// We only make the Supabase client once, and share it. This holds the
// "promise" of it, so two calls at the same time don't make two clients.
let authClientPromise = null;

/**
 * Get the Supabase client, or null when login is turned off.
 *
 * Input:  nothing (it asks GET /api/auth-config the first time)
 * Output: a Supabase client, or null if login is off.
 * Example: const client = await getAuthClient();
 *          await client.auth.getSession()  gives you  {data: {session: ...}}
 */
function getAuthClient() {
  if (authClientPromise === null) {
    authClientPromise = makeAuthClient();
  }
  return authClientPromise;
}

/**
 * Ask our server for the Supabase settings and make the client.
 * getAuthClient() calls this once; use getAuthClient() instead.
 *
 * Input:  nothing
 * Output: a Supabase client, or null if login is off.
 * Example: await makeAuthClient()  gives you  a client for https://abc.supabase.co
 */
async function makeAuthClient() {
  const response = await fetch("/api/auth-config");
  const config = await response.json();
  if (!config.login_on) {
    return null;
  }
  // window.supabase comes from the supabase-js script tag on the page.
  return window.supabase.createClient(
    config.supabase_url,
    config.supabase_publishable_key
  );
}

/**
 * Find out who's logged in right now.
 *
 * Input:  nothing
 * Output: the session ({access_token, user, ...}), or null if nobody is.
 *         supabase-js quietly swaps in a fresh token when the old one is
 *         about to run out, so the token in here is always current.
 * Example: (await getSession()).user.email  gives you  "ana@example.com"
 */
async function getSession() {
  const client = await getAuthClient();
  if (client === null) {
    return null;
  }
  const { data } = await client.auth.getSession();
  return data.session;
}

/**
 * Get the headers that prove who the person is, for a request to our server.
 *
 * Input:  nothing
 * Output: {Authorization: "Bearer ..."}, or {} when nobody is logged in or
 *         login is off.
 * Example: fetch("/api/demo/outbox", {headers: await loginHeaders()})
 */
async function loginHeaders() {
  const session = await getSession();
  if (session === null) {
    return {};
  }
  return { Authorization: `Bearer ${session.access_token}` };
}

/**
 * Make sure someone is logged in before showing a page. If nobody is, send
 * them to the login page.
 *
 * Input:  nothing
 * Output: {loginOn, user}. loginOn is false when login is turned off.
 *         user is the logged in person, or null.
 * Example: const { user } = await requireLogin();
 *          user.email  gives you  "ana@example.com"
 */
async function requireLogin() {
  const client = await getAuthClient();
  if (client === null) {
    return { loginOn: false, user: null };
  }
  const session = await getSession();
  if (session === null) {
    // replace() instead of a normal link, so the Back button doesn't bounce
    // them right back to a page they can't see.
    window.location.replace("/login");
    return { loginOn: true, user: null };
  }
  return { loginOn: true, user: session.user };
}

/**
 * Log the person out and take them back to the landing page.
 *
 * Input:  nothing
 * Output: nothing; the browser goes to /.
 * Example: tap "Log out"  gives you  the landing page, logged out
 */
async function logOut() {
  const client = await getAuthClient();
  if (client !== null) {
    await client.auth.signOut();
  }
  window.location.href = "/";
}
