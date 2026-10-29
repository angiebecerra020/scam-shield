/*
  nav.js — The header at the top of every page: the logo, the tabs
  (Home, Live demo, Test it, Dashboard), and Log in / Log out.

  How it fits in: the home page, login, dashboard, demo player, "Call it
  yourself", privacy, terms and 404 pages each have an empty
  <header id="site-header"> and load this file (and header.css for the look).
  We build the header here, so it's written in one place and every page gets
  the same one. To add a tab, add it to NAV_LINKS below.

  When someone is logged in, "Logged in as Ana" sits next to Log out, with
  the name from their profile (or their email before they have one). It
  links to their profile (profile.html).

  The tabs always show, even on a phone (they get their own row under the
  logo), so nobody has to hunt behind a menu to find a page.

  The English | Español switch sits next to Log in, so it's always one tap
  away. The words come from strings.js (via t() in i18n.js), and the header
  builds itself again when the language changes.

  The "Join call" page and the senior's calling app don't get this header on
  purpose. Each does one job in a hurry, and their links hold secrets we don't
  want people wandering away from and losing.
*/

// The tabs in the header, in order. "text" is the key for its words in strings.js.
const NAV_LINKS = [
  // A plain "Home" link too, since not everyone knows the logo goes home.
  { href: "/", text: "nav.home" },
  { href: "/demo", text: "nav.demo" },
  { href: "/try", text: "nav.try" },
  { href: "/dashboard", text: "nav.dashboard" },
];

/**
 * Make one tab for the header, marked as the current page if it is.
 *
 * Input:  link — one entry from NAV_LINKS
 * Output: the <a> element
 * Example: on /dashboard, navLink({href: "/dashboard", text: "nav.dashboard"})
 *          gives you a tab with aria-current="page", so it shows as the page you're on
 */
function navLink(link) {
  const element = document.createElement("a");
  element.href = link.href;
  element.textContent = t(link.text);
  if (link.href === window.location.pathname) {
    element.setAttribute("aria-current", "page");
  }
  return element;
}

/**
 * The logged in person's name from their profile (GET /api/profile), or
 * their email if they haven't saved a profile yet.
 *
 * Input:  session — from getSession() in auth.js
 * Output: the name to show
 * Example: Ana saved her profile  gives you  "Ana"
 *          a brand-new account  gives you  "ana@example.com"
 */
async function myName(session) {
  try {
    const response = await fetch("/api/profile", {
      headers: { Authorization: `Bearer ${session.access_token}` },
    });
    const data = await response.json();
    if (response.ok && data.profile !== null) {
      return data.profile.name;
    }
  } catch (error) {
    // The server didn't answer. The email still says who they are.
  }
  return session.user.email;
}

/**
 * Add Log in or Log out to the header, depending on whether someone is logged in.
 *
 * We can only tell on pages that load auth.js. When login is turned off
 * (no Supabase settings), there's nothing to log in to, so we add nothing.
 *
 * Input:  tools — the element holding the language switch
 * Output: nothing; it adds the link or button.
 * Example: Ana is logged in  gives you  "Logged in as Ana" and a "Log out" button at the end of the header
 */
async function addAccountLink(tools) {
  // We're already on the login page, so a "Log in" link would go nowhere.
  if (window.location.pathname === "/login" || typeof getAuthClient !== "function") {
    return;
  }

  let client;
  try {
    client = await getAuthClient();
  } catch (error) {
    // The server didn't answer. The page will say so; the header just skips this.
    return;
  }
  if (client === null) {
    return;
  }

  const session = await getSession();
  if (session === null) {
    const logIn = document.createElement("a");
    logIn.href = "/login";
    logIn.className = "account-link";
    logIn.textContent = t("nav.logIn");
    tools.appendChild(logIn);
    return;
  }

  const profileLink = document.createElement("a");
  profileLink.href = "/profile";
  profileLink.className = "account-link account-name";
  profileLink.textContent = t("nav.loggedInAs", { name: await myName(session) });
  if (window.location.pathname === "/profile") {
    profileLink.setAttribute("aria-current", "page");
  }
  tools.appendChild(profileLink);

  const logOutButton = document.createElement("button");
  logOutButton.type = "button";
  logOutButton.className = "account-link";
  logOutButton.textContent = t("nav.logOut");
  logOutButton.addEventListener("click", logOut);
  tools.appendChild(logOutButton);
}

/**
 * Build the header: logo, the tabs, the language switch and Log in / Log out.
 *
 * Input:  nothing (it fills in <header id="site-header">)
 * Output: nothing; it updates the page.
 * Example: open any page  gives you  "Scam Shield   Home  Live demo  Test it  Dashboard   Español  Log in"
 */
function buildHeader() {
  const header = document.getElementById("site-header");
  if (header === null) {
    return;
  }

  const brand = document.createElement("a");
  brand.className = "brand";
  brand.href = "/";
  // Our gold shield icon instead of an emoji, so the logo looks the same on
  // every phone. alt is empty because the words right next to it say the name.
  const shield = document.createElement("img");
  shield.src = "/static/icons/favicon.svg";
  shield.alt = "";
  brand.append(shield, "Scam Shield");

  const tabs = document.createElement("nav");
  tabs.className = "site-tabs";
  tabs.setAttribute("aria-label", t("nav.main"));
  for (const link of NAV_LINKS) {
    tabs.appendChild(navLink(link));
  }

  const tools = document.createElement("div");
  tools.className = "header-tools";
  tools.appendChild(languageSwitch());

  // The tabs come after the tools in the page, so on a phone they wrap onto
  // their own row; header.css moves them between the logo and the tools on
  // bigger screens.
  header.replaceChildren(brand, tools, tabs);
  translatePage();
  addAccountLink(tools);
}

// Build the header again in the new language when they flip the switch.
document.addEventListener("language-switched", buildHeader);

buildHeader();
