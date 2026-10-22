/*
  nav.js — The header at the top of every page: the logo, the main links,
  and Log in / Log out.

  How it fits in: landing.html, login.html and index.html (the dashboard)
  each have an empty <header id="site-header"> and load this file. We build
  the header here, so it's written in one place and every page gets the same
  one. To add a link, add it to NAV_LINKS below.

  On a phone the links fold up behind a "Menu" button, so they don't crowd
  the logo. On bigger screens they're always showing (see styles.css).

  The "Join call" page and the senior's calling app don't get this header on
  purpose. Each does one job in a hurry, and their links hold secrets we don't
  want people wandering away from and losing.
*/

// The links in the header, in order.
const NAV_LINKS = [
  { href: "/demo", label: "Demo" },
  { href: "/dashboard#protect", label: "Protect someone" },
  { href: "/dashboard", label: "Dashboard" },
];

/**
 * Make one link for the header, marked as the current page if it is.
 *
 * Input:  link — one entry from NAV_LINKS
 * Output: the <a> element
 * Example: on /dashboard, navLink({href: "/dashboard", label: "Dashboard"})
 *          gives you a link with aria-current="page", so it shows as the page you're on
 */
function navLink(link) {
  const element = document.createElement("a");
  element.href = link.href;
  element.textContent = link.label;
  // Only a link with no "#" part counts as "this page", so "Protect someone"
  // (/dashboard#protect) doesn't light up along with "Dashboard".
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
 * Input:  links — the element holding the header's links
 * Output: nothing; it adds the link or button.
 * Example: Ana is logged in  gives you  a "Log out" button at the end of the header
 */
async function addAccountLink(links) {
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
    logIn.className = "button button-small";
    logIn.textContent = "Log in";
    links.appendChild(logIn);
    return;
  }

  const logOutButton = document.createElement("button");
  logOutButton.type = "button";
  logOutButton.className = "button-link";
  logOutButton.textContent = "Log out";
  logOutButton.addEventListener("click", logOut);
  links.appendChild(logOutButton);
}

/**
 * Open or close the phone menu.
 *
 * Input:  header — the site header; open — true to open it, false to close it
 * Output: nothing; it updates the page.
 * Example: tap "Menu"  gives you  the links, stacked under the logo
 */
function setMenuOpen(header, open) {
  header.classList.toggle("menu-open", open);
  // Tells screen readers whether the menu is open.
  header.querySelector(".menu-button").setAttribute("aria-expanded", String(open));
}

/**
 * Build the header: logo, Menu button (for phones), and the links.
 *
 * Input:  nothing (it fills in <header id="site-header">)
 * Output: nothing; it updates the page.
 * Example: open any page  gives you  "🛡️ Scam Shield   Demo  Protect someone  Dashboard  Log out"
 */
function buildHeader() {
  const header = document.getElementById("site-header");
  if (header === null) {
    return;
  }

  const brand = document.createElement("a");
  brand.className = "brand";
  brand.href = "/";
  brand.textContent = "🛡️ Scam Shield";

  const menuButton = document.createElement("button");
  menuButton.type = "button";
  menuButton.className = "menu-button";
  menuButton.textContent = "Menu";
  menuButton.setAttribute("aria-controls", "site-nav");
  menuButton.addEventListener("click", () => {
    setMenuOpen(header, !header.classList.contains("menu-open"));
  });

  const nav = document.createElement("nav");
  nav.id = "site-nav";
  nav.className = "site-nav";
  nav.setAttribute("aria-label", "Main");
  for (const link of NAV_LINKS) {
    nav.appendChild(navLink(link));
  }
  // Tapping a link closes the menu. That matters for "Protect someone" on
  // the dashboard, which only scrolls the page instead of opening a new one.
  nav.addEventListener("click", (event) => {
    if (event.target.closest("a")) {
      setMenuOpen(header, false);
    }
  });

  header.replaceChildren(brand, menuButton, nav);
  setMenuOpen(header, false);
  addAccountLink(nav);
}

// Escape closes the phone menu, like most menus.
document.addEventListener("keydown", (event) => {
  const header = document.getElementById("site-header");
  if (event.key === "Escape" && header && header.classList.contains("menu-open")) {
    setMenuOpen(header, false);
    header.querySelector(".menu-button").focus();
  }
});

buildHeader();
