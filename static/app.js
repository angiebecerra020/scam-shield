/*
  app.js — Makes the dashboard page interactive.

  How it fits in: index.html loads this file. For now it only asks our server
  "are you running?" (GET /health) and shows the answer on the page. Later it
  will show the live risk meter, reasons, source links and call history.
*/

/**
 * Ask the server if it's running, then show the answer on the page.
 *
 * Input:  nothing (it calls GET /health on our own server)
 * Output: nothing is returned; it updates the "Server status" text.
 * Example: server running in demo mode -> "Server status: online (demo mode)"
 */
async function showServerStatus() {
  const statusElement = document.getElementById("server-status");

  try {
    const response = await fetch("/health");
    const data = await response.json();
    // Always say whether we're in demo mode, so nobody mistakes a
    // scripted demo call for a real one.
    const modeLabel = data.demo_mode ? "demo mode" : "live mode";
    statusElement.textContent = `online (${modeLabel})`;
    statusElement.classList.add("status-ok");
  } catch (error) {
    // If the server can't be reached, say so plainly instead of
    // leaving "checking…" on the screen forever.
    statusElement.textContent = "offline. Is the server running?";
  }
}

showServerStatus();
