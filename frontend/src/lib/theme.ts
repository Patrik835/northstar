import { useEffect, useState } from "react";

// Light or dark. Until the user picks one, the app follows the device setting.
// index.html applies the same choice before the first paint so the page never flashes.
export type Theme = "light" | "dark";

const STORAGE_KEY = "northstar-theme";
const DARK_QUERY = "(prefers-color-scheme: dark)";
const BROWSER_BAR = { light: "#f4efe4", dark: "#151713" } satisfies Record<Theme, string>;

function storedTheme(): Theme | null {
  try {
    const value = window.localStorage.getItem(STORAGE_KEY);
    return value === "light" || value === "dark" ? value : null;
  } catch {
    return null;
  }
}

function deviceTheme(): Theme {
  return window.matchMedia?.(DARK_QUERY).matches ? "dark" : "light";
}

function applyTheme(theme: Theme) {
  document.documentElement.dataset.theme = theme;
  document.querySelector('meta[name="theme-color"]')?.setAttribute("content", BROWSER_BAR[theme]);
}

export function useTheme(): [Theme, (theme: Theme) => void] {
  const [theme, setThemeState] = useState<Theme>(() => storedTheme() ?? deviceTheme());

  useEffect(() => applyTheme(theme), [theme]);

  useEffect(() => {
    const media = window.matchMedia?.(DARK_QUERY);
    if (!media) return;
    const follow = () => {
      if (!storedTheme()) setThemeState(deviceTheme());
    };
    media.addEventListener("change", follow);
    return () => media.removeEventListener("change", follow);
  }, []);

  const setTheme = (next: Theme) => {
    try {
      window.localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // Private windows may block storage; the choice then lasts for this visit only.
    }
    setThemeState(next);
  };
  return [theme, setTheme];
}
