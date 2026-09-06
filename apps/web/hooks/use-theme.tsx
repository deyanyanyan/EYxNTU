"use client";

import { useCallback, useEffect, useState } from "react";

type Theme = "light" | "dark";

export function useTheme() {
  const [theme, setTheme] = useState<Theme>("light");

  useEffect(() => {
    const stored = (localStorage.getItem("lms_theme") as Theme | null) ?? (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    apply(stored);
  }, []);

  const apply = (t: Theme) => {
    document.documentElement.classList.toggle("dark", t === "dark");
    localStorage.setItem("lms_theme", t);
    setTheme(t);
  };

  const toggle = useCallback(() => apply(theme === "dark" ? "light" : "dark"), [theme]);
  return { theme, toggle };
}
