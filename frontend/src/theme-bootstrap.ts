// Applies the saved (or system) theme as early as possible — imported first in
// main.tsx so it runs before React renders. It lived as an inline <script> in
// index.html until Phase 6; moving it into the bundle lets the production CSP
// forbid inline scripts (script-src 'self') without a flash-of-wrong-theme for
// the common case, since this module is the first thing the entry chunk runs.
try {
  const saved = localStorage.getItem("blackbox.theme");
  const prefersDark = window.matchMedia?.("(prefers-color-scheme: dark)").matches;
  if (saved === "dark" || (!saved && prefersDark)) {
    document.documentElement.classList.add("dark");
  }
} catch {
  // localStorage/matchMedia unavailable (private mode, SSR) — default to light.
}
