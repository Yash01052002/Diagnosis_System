import { useCallback, useEffect, useState } from "react";

export type Theme = "light" | "dark";
const KEY = "blackbox.theme";

function current(): Theme {
  return document.documentElement.classList.contains("dark") ? "dark" : "light";
}

/** Reads/writes the theme class on <html>, persisted to localStorage. The
 *  initial class is set by a pre-paint script in index.html to avoid a flash. */
export function useTheme(): { theme: Theme; toggle: () => void } {
  const [theme, setTheme] = useState<Theme>(current);

  useEffect(() => {
    const root = document.documentElement;
    root.classList.toggle("dark", theme === "dark");
    try {
      localStorage.setItem(KEY, theme);
    } catch {
      // ignore storage failures (private mode)
    }
  }, [theme]);

  const toggle = useCallback(
    () => setTheme((t) => (t === "dark" ? "light" : "dark")),
    [],
  );

  return { theme, toggle };
}
