/*
  nav.js — The header at the top of every page: the logo, the tabs
  (Home, About us, Dashboard, Q&A, Test it, Live demo), and Log in / Log out.

  How it fits in: the home page, login, dashboard, demo player, "Call it
  yourself", Q&A, privacy, terms and 404 pages each have an empty
  <header id="site-header"> and load this file (and header.css for the look).
  We build the header here, so it's written in one place and every page gets
  the same one. To add a tab, add it to NAV_LINKS below.

  When someone is logged in, Log out sits at the right. Their profile and
  the "How to set up" page are linked from inside the dashboard (index.html),
  not from here.

  The tabs always show, even on a phone (they get their own row under the
  logo), so nobody has to hunt behind a menu to find a page.

  The English | Español switch sits next to Log in, so it's always one tap
  away. The words come from strings.js (via t() in i18n.js), and the header
  builds itself again when the language changes.

  The "Join call" page doesn't get this header on purpose. It does one job in
  a hurry, and its link holds a secret we don't want people wandering away
  from and losing.
*/

// The tabs in the header, in order. "text" is the key for its words in strings.js.
const NAV_LINKS = [
  // A plain "Home" link too, since not everyone knows the logo goes home.
  { href: "/", text: "nav.home" },
  { href: "/about", text: "nav.about" },
  { href: "/dashboard", text: "nav.dashboard" },
  { href: "/qa", text: "nav.qa" },
  { href: "/try", text: "nav.try" },
  { href: "/demo", text: "nav.demo" },
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
 * Add Log in or Log out to the header, depending on whether someone is logged in.
 *
 * We can only tell on pages that load auth.js. When login is turned off
 * (no Supabase settings), there's nothing to log in to, so we add nothing.
 *
 * Input:  tools — the element holding the language switch
 * Output: nothing; it adds the link or button.
 * Example: Ana is logged in  gives you  a "Log out" button at the end of the header
 */
async function addAccountLink(tools, tabs) {
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

  // Logged in: their call log and their account (the profile page).
  if (tabs) {
    tabs.appendChild(navLink({ href: "/calls", text: "nav.callLog" }));
    tabs.appendChild(navLink({ href: "/profile", text: "nav.account" }));
  }

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
 * Example: open any page  gives you  "Scam Shield   Home  About us  Dashboard  Q&A  Test it  Live demo   Español  Log in"
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
  addAccountLink(tools, tabs);
}

// Build the header again in the new language when they flip the switch.
document.addEventListener("language-switched", buildHeader);

buildHeader();
