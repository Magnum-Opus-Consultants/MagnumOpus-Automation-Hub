"use client";

import { useEffect, useState } from "react";

type Theme = "light" | "dark";

const KEY = "sentinel-theme";

function read(): Theme {
  try {
    const t = localStorage.getItem(KEY);
    if (t === "light" || t === "dark") return t;
  } catch {
    // Storage can throw outright (private windows, blocked site data).
  }
  try {
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  } catch {
    return "light";
  }
}

/**
 * Light/dark switch, as in the Filament panels.
 *
 * The class is already on <html> before paint (see THEME_INIT in layout.tsx);
 * this only mirrors that into state so the icon matches, then flips both on
 * click. Renders a placeholder until mounted so the server and client markup
 * agree — the real value isn't knowable during SSR.
 */
export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme | null>(null);

  useEffect(() => {
    // The applied theme lives on <html> (set pre-paint in layout.tsx) and in
    // storage, neither readable during SSR, so it cannot seed useState directly.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setTheme(document.documentElement.classList.contains("dark") ? "dark" : read());
  }, []);

  function apply(next: Theme) {
    setTheme(next);
    document.documentElement.classList.toggle("dark", next === "dark");
    try {
      localStorage.setItem(KEY, next);
    } catch {
      // Preference just won't persist; the toggle still works this session.
    }
  }

  if (theme === null) {
    return <span className="h-9 w-9 shrink-0" aria-hidden />;
  }

  const isDark = theme === "dark";
  return (
    <button
      onClick={() => apply(isDark ? "light" : "dark")}
      title={isDark ? "Switch to light mode" : "Switch to dark mode"}
      aria-label={isDark ? "Switch to light mode" : "Switch to dark mode"}
      className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-ink-2 transition hover:bg-subtle hover:text-ink focus-ring"
    >
      {isDark ? (
        /* Sun — click to go light */
        <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round">
          <circle cx="12" cy="12" r="4" />
          <path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M19.1 4.9l-1.4 1.4M6.3 17.7l-1.4 1.4" />
        </svg>
      ) : (
        /* Moon — click to go dark */
        <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round">
          <path d="M21 12.8A8.5 8.5 0 1 1 11.2 3a6.5 6.5 0 0 0 9.8 9.8z" />
        </svg>
      )}
    </button>
  );
}
